import logging
import math
import time
import threading
from queue import Queue
from typing import Callable, Iterator, Union

import meshtastic
import meshtastic.serial_interface
import meshtastic.version
import minify_html_onepass
from pubsub import pub

from meshpages.air_traffic_control import AirTrafficControl
from meshpages.channel_presets import ChannelPresets
from meshpages.models import Config, ResponsePacket, User
from meshpages.utils import compress_payload, decode_packet, decompress_payload, encode_packet

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Buffer offset for the packet header
BUFFER_OFFSET = 7
# Maximum payload length for a single packet in Meshtastic
DATA_PAYLOAD_LEN = 200
# Maximum total payload length for a response
TOTAL_ALLOWED_PAYLOAD_LENGTH = 200
# Meshtastic portnum for binary data transmission (used for encoded packets)
PRIVATE_APP = "PRIVATE_APP"
# Meshtastic portnum for text messages (used for plain text responses)
TEXT_MESSAGE_APP = "TEXT_MESSAGE_APP"
# Meshtastic portnum for mesh routing information
ROUTING_APP = "ROUTING_APP"
# Supported content types for responses from endpoint handlers
INTENDED_RETURN_TYPES = ["html", "text"]


class MeshPageServer:
    """
    Server for handling HTTP-like page requests from remote mesh nodes.

    Listens for incoming requests from Meshtastic mesh clients, routes them to
    registered endpoint handlers, and sends back responses with multi-packet support
    and compression. Manages resource allocation through air traffic control to
    prevent channel congestion.
    """

    def __init__(
        self,
        usb_interface: str = None,
        loop_interval: float = 1.0,  # in seconds
        timeout: int = 60,  # in seconds
        courtousy_interval: float = 2.5,  # in seconds
        message_ack: str = True,  # True for TCP style, False for UDP style of message sending
        air_traffic_control_config: Union[Config, ChannelPresets] = ChannelPresets.LONG_FAST,  # in Config or ChannelPresets
        air_traffic_control_target_utilization_percent: float = 50.0,  # in percent
        air_traffic_control_window_seconds: float = 10.0,  # in seconds
        air_traffic_control_meshtastic_overhead_bytes: int = 20,  # in bytes
    ):
        """
        Initialize the mesh page server and connect to the mesh network.

        Parameters:
            usb_interface (str, optional): USB device path for the Meshtastic radio. Defaults to None (auto-detect).
            loop_interval (float): How often to process the user queue (seconds). Defaults to 1.0.
            timeout (int): Maximum time to wait before dropping a client request (seconds). Defaults to 60.
            courtousy_interval (float): Delay between sending consecutive chunks (seconds). Defaults to 0.3.
            air_traffic_control_config (Union[Config, ChannelPresets]): LoRa radio configuration. Defaults to LONG_FAST preset.
            air_traffic_control_target_utilization_percent (float): Target channel utilization (0-100). Defaults to 50%.
            air_traffic_control_window_seconds (float): Time window for utilization calculation (seconds). Defaults to 10.0.
            air_traffic_control_meshtastic_overhead_bytes (int): Protocol overhead per packet (bytes). Defaults to 20.

        Raises:
            ValueError: If no valid node ID is found on the connected Meshtastic device.
            Exception: If connection to the Meshtastic serial interface fails.
        """
        # Subscribe to the Meshtastic pubsub system to receive all incoming packets
        pub.subscribe(self._on_receive, "meshtastic.receive")
        self.node_info = None

        try:
            # Connect to the Meshtastic radio via USB serial interface
            self.interface = meshtastic.serial_interface.SerialInterface(usb_interface)

            # Retrieve local device information from the connected radio
            self.node_info = self.interface.getMyNodeInfo()

            # Extract this node's unique identifier from device info
            self.node_id = self.node_info.get("user", {}).get("id", "")

            # Node ID is required for communication validation
            if not self.node_id:
                logger.error("No node ID found")
                raise ValueError("No node ID found")
            logger.info(f"Connected to node with ID `{self.node_id}`")
        except Exception as e:
            logger.error(f"Error in server: {e}")
            logger.error(f"Failed to create serial interface with interface {usb_interface}")
            raise

        # Dictionary mapping request paths to handler functions and their response types
        self.routes = {}
        # How often (in seconds) to wake up and process the response queue
        self.loop_interval = loop_interval
        # Delay between sending consecutive response chunks to prevent overwhelming receivers
        self.courtousy_interval = courtousy_interval
        # Maximum time (in seconds) to wait before dropping a timed-out client request
        self.client_timeout_interval = timeout
        # Queue to buffer User objects awaiting response transmission
        self.user_queue = Queue()
        # Air traffic control instance to regulate transmission rates and prevent congestion
        self.air_traffic_control = AirTrafficControl(
            config=air_traffic_control_config,
            target_utilization_percent=air_traffic_control_target_utilization_percent,
            window_seconds=air_traffic_control_window_seconds,
            meshtastic_overhead_bytes=air_traffic_control_meshtastic_overhead_bytes,
        )

        # Whether to use TCP-style acknowledgments (True) or UDP-style fire-and-forget (False)
        self.message_ack = message_ack
        # Node ID of the client currently being transmitted to (tracked for retry matching)
        self.current_client_node_id = None
        # Last chunk sent to current client (cached for retry attempts on transmission error)
        self.current_client_message = None
        # Response type of current message: "html" (binary) or "text" (plaintext)
        self.response_type = None
        # Synchronization primitive: sender waits on this for ACK, receiver signals completion
        self.response_event = threading.Event()
        # Maximum time (seconds) to wait for an ACK before timing out and treating as failure
        self.response_event_timeout = 10.0
        # Maximum number of transmission retries per chunk before giving up on client
        self.event_retries = 3
        # Current retry attempt count for the chunk being transmitted
        self.current_event_retries = 0
        # ACK status flag: True = success/ready for next chunk, False = failure/timeout
        self.current_send_status = True

    def _reset_client_state(self) -> None:
        """
        Reset the server's client state after completing a transmission to the current client.

        Clears all tracking data for the current client being served, including node ID,
        buffered message, response type, and acknowledgment state. This should be called when
        transmission completes (either successfully after all chunks sent or after max retries exceeded).
        Resets flags to allow the next client transmission to proceed cleanly.

        Parameters:
            None

        Returns:
            None
        """
        # Clear tracked client so retries don't match old ACKs
        self.current_client_node_id = None
        # Clear cached chunk to free memory and prevent stale retries
        self.current_client_message = None
        # Clear cached response type (html or text)
        self.response_type = None
        # Reset to ready state for next client transmission
        self.current_send_status = True
        # Reset retry counter to 0 for next chunk
        self.current_event_retries = 0

    def _get_chunks(
        self,
        payload: str | bytes,
        status_code: int = 200,
    ) -> Iterator[ResponsePacket]:
        """
        Chunk a payload into transmission-sized packets.

        Splits payload respecting maximum packet size limits while generating ResponsePacket
        objects with appropriate chunk metadata. Handles both successful responses (status 200)
        and error responses separately.

        Parameters:
            payload (str | bytes): The response payload to chunk (HTML, text, or compressed bytes).
            status_code (int): HTTP status code (200 for success, other values for errors). Defaults to 200.

        Yields:
            ResponsePacket: Response packets ready for transmission, one chunk per iteration.

        Raises:
            ValueError: If payload exceeds maximum chunk count (255 chunks).
        """
        # Calculate safe payload size: reserve space for packet header and metadata
        payload_length = DATA_PAYLOAD_LEN - BUFFER_OFFSET
        logger.debug(f"DATA_PAYLOAD_LEN: {DATA_PAYLOAD_LEN}")
        logger.debug(f"Buffer offset: {BUFFER_OFFSET}")
        logger.debug(f"Payload length: {payload_length}")

        # Error responses are always sent as single chunk (not split across multiple packets)
        if status_code != 200:
            if isinstance(payload, str):
                raw = payload.encode("utf-8")
                as_str = True
            else:
                raw = bytes(payload)
                as_str = False

            # Truncate oversized error messages to fit in single chunk
            if len(raw) > payload_length:
                # TODO: Support oversized error messages (multi-chunk errors, truncation indicator, or reject earlier in stack)
                raw = raw[:payload_length]
            error_content: str | bytes = raw.decode("utf-8", errors="replace") if as_str else raw
            yield ResponsePacket(
                content=error_content,
                status_code=status_code,
                current_chunk_id=1,
                total_chunks=1,
            )
            return

        # Calculate total number of chunks needed for successful response
        total_chunks = math.ceil(len(payload) / payload_length)

        # Handle edge case: empty payload should be sent as single blank chunk
        total_chunks = total_chunks if total_chunks > 0 else 1

        # Prevent payload from exceeding maximum packet count (255 is the limit)
        if total_chunks > 255:
            total_chunks = 1
            status_code = 500
            payload = "Too many chunks to send. Please try again later.".encode("utf-8")

        logger.debug(f"Total chunks: {total_chunks}")
        # Yield each chunk in order (chunk IDs are 1-indexed from 1 to total_chunks)
        for chunk_id in range(total_chunks):
            response_packet = ResponsePacket(
                content=payload[chunk_id * payload_length : (chunk_id + 1) * payload_length],
                status_code=status_code,
                current_chunk_id=chunk_id + 1,
                total_chunks=total_chunks,
            )
            yield response_packet

    def _send_chunked_response(
        self,
        response_string: str,
        response_type: str,
        status_code: int,
        destination_id: str,
    ) -> None:
        """
        Send a response to a client, splitting into chunks and applying compression.

        Handles HTML responses by minifying and compressing them. Text responses are sent
        as-is. Applies backoff delays based on channel utilization and includes courtesy
        delays between chunks to prevent overwhelming the receiver.

        Parameters:
            response_string (str): The response content (HTML or plain text).
            response_type (str): Response format - "html" or "text". Determines compression and formatting.
            status_code (int): HTTP status code (200 for success, 4xx/5xx for errors).
            destination_id (str): Target node ID to send response to.

        Returns:
            None

        Raises:
            ValueError: If response_type is not "html" or "text".
        """
        if response_type == "html":
            # Remove unnecessary whitespace and HTML comments from the response to reduce size
            response_string = minify_html_onepass.minify(response_string)
            logger.debug(f"Minified response size: {len(response_string)} characters")

            # Apply Brotli compression with quality 11 (maximum compression) for further size reduction
            compressed_response_string = compress_payload(response_string)
            logger.debug(f"Compressed response size: {len(compressed_response_string)} bytes")

            for response_packet in self._get_chunks(compressed_response_string, status_code=status_code):
                # Encode the response packet into a byte sequence
                chunk = encode_packet(response_packet)
                logger.debug(f"Sending chunk {response_packet.current_chunk_id} of {response_packet.total_chunks} to {destination_id}")

                # Prepare for TCP-style acknowledgment: set up state for potential retries
                if self.message_ack:
                    # Track which client we're sending to (used in _on_receive for ACK matching)
                    self.current_client_node_id = destination_id
                    # Cache the chunk for retry if ACK fails
                    self.current_client_message = chunk
                    # Cache response type for retry logic (determines sendData vs sendText)
                    self.response_type = response_type
                    # Reset ACK status to False: assume failure until proven otherwise
                    self.current_send_status = False
                    # Clear event to avoid catching stale signals from previous transmissions
                    self.response_event.clear()

                # Check channel utilization and apply backoff delay if needed
                self.air_traffic_control.apply_backoff_delay()

                # Send the encoded packet to the destination node with acknowledgment request
                self.interface.sendData(chunk, destinationId=destination_id, wantAck=self.message_ack)

                # Wait for ACK (sets current_send_status and signals event when received or timed out)
                if self.message_ack:
                    self.response_event.wait(self.response_event_timeout)

                # Check ACK result: if failed/timed out after retries, abort remaining chunks
                if self.message_ack and not self.current_send_status:
                    logger.warning(f"Stopping transmission to {destination_id}: client unreachable or timed out")
                    self._reset_client_state()
                    return

                # Record packet transmission for air traffic control tracking
                self.air_traffic_control.add_packet_sent(len(chunk))

                # Stop sending further chunks if error status (error responses are single-chunk only)
                if status_code != 200:
                    return

                # Courtesy delay between chunks to give receiver time to process
                time.sleep(self.courtousy_interval)
        elif response_type == "text":
            # Send plain text responses as a sequence of TEXT_MESSAGE packets, one per chunk
            for response_packet in self._get_chunks(response_string, status_code=status_code):
                # Get the current chunk of the response
                chunk = response_packet.content
                logger.debug(f"Sending chunk {response_packet.current_chunk_id} of {response_packet.total_chunks} to {destination_id}")

                # Prepare for TCP-style acknowledgment: set up state for potential retries
                if self.message_ack:
                    # Track which client we're sending to (used in _on_receive for ACK matching)
                    self.current_client_node_id = destination_id
                    # Cache the chunk for retry if ACK fails
                    self.current_client_message = chunk
                    # Cache response type for retry logic (determines sendData vs sendText)
                    self.response_type = response_type
                    # Reset ACK status to False: assume failure until proven otherwise
                    self.current_send_status = False
                    # Clear event to avoid catching stale signals from previous transmissions
                    self.response_event.clear()

                # Check channel utilization and apply backoff delay if needed
                self.air_traffic_control.apply_backoff_delay()

                # Send the text message to the destination node with acknowledgment request
                self.interface.sendText(chunk, destinationId=destination_id, wantAck=self.message_ack)

                # Wait for ACK (sets current_send_status and signals event when received or timed out)
                if self.message_ack:
                    self.response_event.wait(self.response_event_timeout)

                # Check ACK result: if failed/timed out after retries, abort remaining chunks
                if self.message_ack and not self.current_send_status:
                    logger.warning(f"Stopping transmission to {destination_id}: client unreachable or timed out")
                    self._reset_client_state()
                    return

                logger.info(f"Sent text message to {destination_id}: {response_packet.content}")

                # Record packet transmission for air traffic control tracking
                self.air_traffic_control.add_packet_sent(len(response_packet.content))

                # Stop sending further chunks if error status (error responses are single-chunk only)
                if status_code != 200:
                    return

                # Courtesy delay between chunks to give receiver time to process
                time.sleep(self.courtousy_interval)
        else:
            logger.error(f"Invalid response type: {response_type}. Must be one of: {INTENDED_RETURN_TYPES}")
            raise ValueError(f"Invalid response type: {response_type}. Must be one of: {INTENDED_RETURN_TYPES}")

    def _throw_error_response(self, from_id: str, error_message: str, status_code: int) -> None:
        """
        Queue an error response to be sent back to a client.

        Creates a User object with error details and queues it for transmission.
        Error responses are always sent as plain text type.

        Parameters:
            from_id (str): The client's node ID to send the error to.
            error_message (str): The error message content to send.
            status_code (int): HTTP status code (e.g., 400, 404, 500).

        Returns:
            None
        """
        self.user_queue.put(
            User(
                from_id=from_id,
                result=error_message,
                intended_return_type="text",
                status_code=status_code,
                time_received=time.time(),
            )
        )

    def _on_receive(
        self,
        packet,
        interface: meshtastic.serial_interface.SerialInterface,
    ) -> None:
        """
        Handle incoming requests from mesh clients.

        Callback invoked by the Meshtastic pubsub system for each received packet.
        Extracts route requests, validates them against registered endpoints, and
        queues responses for processing. Automatically sends 404 errors for unknown routes.

        Parameters:
            packet (dict): The received Meshtastic packet containing decoded message data.
            interface (meshtastic.serial_interface.SerialInterface): The radio interface reference.

        Returns:
            None
        """
        # Get the decoded message and extract the text
        decoded_message = packet.get("decoded", {})
        portnum = decoded_message.get("portnum", "")
        if portnum in [TEXT_MESSAGE_APP, PRIVATE_APP, ROUTING_APP]:
            # Extract the sender's node ID
            from_id = packet.get("fromId", "")
            if not from_id:
                # Defensive check: from_id should always be present, but handle gracefully if missing
                logger.warning("No from ID found in packet")
                return

            # Perform the retry logic for the current client if needed
            if portnum == ROUTING_APP and from_id == self.current_client_node_id:
                print(f"Received routing message from current client: {decoded_message}")
                # Get the routing metadata from the decoded message
                routing = decoded_message.get("routing", {})
                # Get the error reason from the routing metadata
                error_reason = routing.get("errorReason", None)
                # Convert the error reason to None if it is "NONE"
                error_reason = None if error_reason == "NONE" else error_reason
                print(type(error_reason))
                print(f"Error reason: {error_reason}")

                # Determine retry logic: error_reason present means transmission failed at client
                if error_reason and self.current_event_retries < self.event_retries:
                    # Client reported an error and we haven't exceeded max retries
                    if self.current_client_message and self.response_type:
                        logger.info(f"Retrying message to {self.current_client_node_id} (attempt {self.current_event_retries + 1}/{self.event_retries})")
                        # Resend the cached chunk using the same method (sendData for html, sendText for text)
                        if self.response_type == "html":
                            self.interface.sendData(self.current_client_message, destinationId=self.current_client_node_id, wantAck=self.message_ack)
                        elif self.response_type == "text":
                            self.interface.sendText(self.current_client_message, destinationId=self.current_client_node_id, wantAck=self.message_ack)
                        else:
                            logger.error(f"Invalid response type: {self.response_type}. Must be one of: {INTENDED_RETURN_TYPES}")
                    # Increment retry counter for this chunk
                    self.current_event_retries += 1
                # Max retries exceeded: client is unreachable, abort transmission
                elif self.current_event_retries >= self.event_retries:
                    logger.error(f"Failed to send message to {self.current_client_node_id} after {self.event_retries} attempts")
                    # Signal failure to the sender: it will short-circuit and stop sending
                    self.current_send_status = False
                    self.response_event.set()
                # Successful ACK: no error_reason means message was received and processed
                else:
                    # Reset retry counter for next chunk
                    self.current_event_retries = 0
                    # Signal success to the sender: it will continue to next chunk
                    self.current_send_status = True
                    self.response_event.set()
                return

            # Any ROUTING_APP not for the current client we're tracking, ignore it
            elif portnum == ROUTING_APP:
                logger.debug(f"Ignoring ROUTING_APP from {from_id}: not the tracked client")
                return

            # Extract message data (PRIVATE_APP uses binary payload, TEXT_MESSAGE_APP uses text field)
            elif portnum == PRIVATE_APP:
                # Binary data for encoded requests
                text = decoded_message.get("payload", b"")

            elif portnum == TEXT_MESSAGE_APP:
                # Plain text requests
                text = decoded_message.get("text", "").strip().lower()

            # Any other portnum is invalid, ignore it
            else:
                logger.error(f"Invalid portnum: {portnum}")
                return

            logger.info(f"Received a message from {from_id}: {text if isinstance(text, str) else f'<binary data {len(text)} bytes>'}")

            message_request_type = None

            try:
                # Attempt to decode as a binary packet (indicates web client request)
                decoded_packet = decode_packet(text)
                decompressed_payload = decompress_payload(decoded_packet.content)
                if decompressed_payload:
                    # Successfully decoded and decompressed: this is a web client request
                    text = decompressed_payload
                    message_request_type = "html"
                else:
                    # Decoded but decompressed to empty: treat as text fallback
                    logger.error("No decompressed payload found")
                    message_request_type = "text"
            except Exception as e:
                # Failed to decode as packet: this is a plain text request (Meshtastic app)
                logger.error(f"Error decoding packet: {e}")
                message_request_type = "text"

            # Check if the message is a valid endpoint
            if text and text in self.routes:
                # Get the function and intended return type associated with the endpoint
                func = self.routes[text]["func"]
                intended_return_type = self.routes[text]["intended_return_type"]

                # Validate that the client type matches the endpoint's expected type
                # Send user-friendly error messages for common mismatches
                if message_request_type == "text" and intended_return_type == "html":
                    self._throw_error_response(
                        from_id,
                        "This endpoint requires the MeshPages web client. Please use the web client instead of the Meshtastic app.",
                        400,
                    )
                    return
                elif message_request_type == "html" and intended_return_type == "text":
                    self._throw_error_response(
                        from_id,
                        "This endpoint requires the Meshtastic app. Please use the Meshtastic app instead of the MeshPages web client.",
                        400,
                    )
                    return
                # Catch unexpected request types (edge case: malformed or hacked requests)
                elif message_request_type != intended_return_type:
                    self._throw_error_response(
                        from_id,
                        f"Message request type {message_request_type} does not match intended return type {intended_return_type}",
                        400,
                    )
                    return

                # Call the function associated with the endpoint
                result = func()

                # Set the status code to 200
                status_code = 200

                # Add the user to the user queue
                self.user_queue.put(
                    User(
                        from_id=from_id,
                        result=result,
                        intended_return_type=intended_return_type,
                        status_code=status_code,
                        time_received=time.time(),
                    )
                )

                return
            else:
                # Route not found: compile list of available routes to suggest to the user
                text_routes = []
                html_routes = []

                # Categorize routes by their intended return type
                for route in self.routes:
                    if self.routes[route]["intended_return_type"] == "text":
                        text_routes.append(route)
                    elif self.routes[route]["intended_return_type"] == "html":
                        html_routes.append(route)

                # Format routes as newline-separated lists for the error message
                text_routes_str = "\n".join(text_routes)
                html_routes_str = "\n".join(html_routes)

                # Return a 404 error with helpful suggestions about available routes (text routes for Meshtastic App, html routes for MeshPages Web Client)
                self._throw_error_response(
                    from_id,
                    f"Invalid. Choose from the following routes:\nMeshtastic App:\n{text_routes_str}\nMeshPages Web Client:\n{html_routes_str}",
                    404,
                )

                return

    def _process_user_queue(self) -> None:
        """
        Process all queued client responses and send them to destination nodes.

        Drains the user queue, handling timeout-expired requests and sending valid
        responses through the mesh network. Continues processing until queue is empty.

        Parameters:
            None

        Returns:
            None
        """
        # Drain the entire queue of pending responses
        while not self.user_queue.empty():
            # Get the next client request from the queue
            user: User = self.user_queue.get()
            # Process the request and send response, with error handling
            try:
                # Check if too much time has passed since the client made this request
                if time.time() - user.time_received > self.client_timeout_interval:
                    logger.warning(f"User {user.from_id} has timed out after {self.client_timeout_interval} seconds")
                # Send the response to the client
                else:
                    self._send_chunked_response(user.result, user.intended_return_type, user.status_code, user.from_id)
            except Exception as e:
                # Log transmission errors but continue processing the queue
                logger.error(f"Error processing user queue: {e}")
                pass
            finally:
                # Mark the task as complete (required for Queue.join() to work properly)
                self.user_queue.task_done()

    def page(
        self,
        path: str,
        intended_return_type: str = "html",
    ) -> Callable[[Callable], Callable]:
        """
        Decorator to register an endpoint handler for a GET-like request path.

        Usage:
            @server.page("/index.html", intended_return_type="html")
            def handle_index():
                return "<html>...</html>"

        Parameters:
            path (str): The request path to match (e.g., "/index.html" or "/status").
            intended_return_type (str): Response format - "html" or "text". Defaults to "html".

        Returns:
            Callable[[Callable], Callable]: Decorator function that registers the handler and returns it unchanged.

        Raises:
            ValueError: If intended_return_type is not "html" or "text".
        """

        # Define the inner decorator function that performs the registration
        def decorator(func: Callable):
            logger.info(f"GET request for {path}")
            # Store the handler function and its response type in the routes dictionary
            self.routes[path] = {
                "func": func,
                "intended_return_type": intended_return_type,
            }
            return func

        # Validate the response type before registering the handler
        if intended_return_type not in INTENDED_RETURN_TYPES:
            logger.error(f"Invalid intended return type: {intended_return_type}. Must be one of: {INTENDED_RETURN_TYPES}")
            raise ValueError(f"Invalid intended return type: {intended_return_type}. Must be one of: {INTENDED_RETURN_TYPES}")

        return decorator

    def run(self) -> None:
        """
        Start the server main loop and begin processing incoming requests.

        Continuously monitors for incoming client requests and processes the response
        queue at regular intervals. Logs node information on startup and handles
        graceful shutdown on exceptions.

        This is a blocking call that runs until an exception occurs or the process is terminated.

        Parameters:
            None

        Returns:
            None
        """
        try:
            # Log startup information about the connected Meshtastic device
            logger.info(f"API Version: {meshtastic.version.get_active_version()}")
            logger.info(f"Node Number: {self.node_info.get('num', "")}")
            logger.info(f"User: {self.node_info.get('user', {})}")
            logger.info(f"Position: {self.node_info.get('position', {})}")
            logger.info(f"Device Metrics: {self.node_info.get('deviceMetrics', {})}")
            logger.info(f"Is Favorite: {self.node_info.get('isFavorite', False)}")

            # Main server loop: continuously process incoming requests and outgoing responses
            while True:
                # Wake up periodically to process queued responses
                time.sleep(self.loop_interval)

                # Send all queued responses to their destination clients
                self._process_user_queue()
        except Exception as e:
            logger.error(f"Error in server: {e}")
            logger.info("Shutting down...")
            self.interface.close()

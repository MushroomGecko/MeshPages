import inspect
import logging
import math
import os
import threading
import time
from queue import Queue
from typing import Callable, Iterator, Literal, Union

import meshtastic
import meshtastic.ble_interface
import meshtastic.serial_interface
import meshtastic.stream_interface
import meshtastic.tcp_interface
import meshtastic.version
import minify_html_onepass
from pubsub import pub

from meshpages.air_traffic_control import AirTrafficControl
from meshpages.enums import ChannelPresets, ReturnTypes, StatusCodes
from meshpages.models import Config, ResponsePacket, User
from meshpages.types import MeshType
from meshpages.utils import (
    CHUNKABLE_STATUS_CODES,
    compress_payload,
    decode_packet,
    decompress_payload,
    encode_packet,
    parse_hostname,
    parse_parameters,
)

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    # Allow environment variable to override log level (default: INFO)
    log_level = os.environ.get("PYTHONLOGLEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, log_level))
    # Prevent duplicate logs by not propagating to parent loggers
    logger.propagate = False

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
# Supported content types for responses from endpoint handlers
INTENDED_RETURN_TYPES = [ReturnTypes.HTML, ReturnTypes.TEXT, ReturnTypes.BOTH]


class MeshPagesServer:
    """
    Server for handling HTTP-like page requests from remote mesh nodes.

    Listens for incoming requests from Meshtastic mesh clients, routes them to
    registered endpoint handlers, and sends back responses with multi-packet support
    and compression. Manages resource allocation through air traffic control to
    prevent channel congestion.
    """

    def __init__(
        self,
        connection_type: Literal["usb", "bluetooth", "host"] = "usb",
        interface_path: str = None,  # Path for connection: device path for USB (e.g. /dev/ttyUSB0), device name/MAC for Bluetooth (e.g. MESH_1111 or AA:BB:CC:DD:EE:FF), or "hostname:port" for host
        loop_interval: float = 1.0,  # in seconds
        timeout: int = 300,  # in seconds
        courtousy_interval: float = 3.0,  # in seconds
        message_ack: str = True,  # True for TCP style, False for UDP style of message sending
        air_traffic_control_config: Union[Config, ChannelPresets] = ChannelPresets.LONG_FAST,  # in Config or ChannelPresets
        air_traffic_control_target_utilization_percent: float = 50.0,  # in percent
        air_traffic_control_window_seconds: float = 10.0,  # in seconds
        air_traffic_control_meshtastic_overhead_bytes: int = 20,  # in bytes
    ):
        """
        Initialize the mesh page server and connect to the mesh network.

        Parameters:
            connection_type (str): The type of connection to use ("usb", "bluetooth", "host"). Defaults to "usb".
            interface_path (str, optional): The path to the interface to use. Defaults to None (auto-detect).
                For USB: device path (e.g., '/dev/ttyUSB0')
                For Bluetooth: device name (e.g., 'MESH_1111') or MAC address (e.g., 'AA:BB:CC:DD:EE:FF')
                For host: "hostname:port" format (e.g., '192.168.1.100:4403')
            loop_interval (float): How often to process the user queue (seconds). Defaults to 1.0.
            timeout (int): Maximum time to wait before dropping a client request (seconds). Defaults to 300.
            courtousy_interval (float): Delay between sending consecutive chunks (seconds). Defaults to 3.0.
            air_traffic_control_config (Union[Config, ChannelPresets]): LoRa radio configuration. Defaults to LONG_FAST preset.
            air_traffic_control_target_utilization_percent (float): Target channel utilization (0-100). Defaults to 50%.
            air_traffic_control_window_seconds (float): Time window for utilization calculation (seconds). Defaults to 10.0.
            air_traffic_control_meshtastic_overhead_bytes (int): Protocol overhead per packet (bytes). Defaults to 20.

        Raises:
            ValueError: If no valid node ID is found on the connected Meshtastic device.
            Exception: If connection to the Meshtastic interface fails.
        """
        # Subscribe to the Meshtastic pubsub system to receive all incoming packets
        pub.subscribe(self._on_receive, "meshtastic.receive")
        self.node_info = None

        try:
            # Connect to the Meshtastic radio via the specified interface
            if connection_type == "usb":
                self.interface = meshtastic.serial_interface.SerialInterface(interface_path)
            elif connection_type == "bluetooth":
                self.interface = meshtastic.ble_interface.BLEInterface(interface_path)
            elif connection_type == "host":
                if not interface_path:
                    raise ValueError("Host connection requires interface_path in format 'hostname:port' or 'hostname' (defaults to port 4403)")
                hostname, port = parse_hostname(interface_path)
                self.interface = meshtastic.tcp_interface.TCPInterface(hostname, portNumber=port)
            else:
                raise ValueError(
                    f"Invalid connection configuration. Got connection_type={connection_type!r}, interface_path={interface_path!r}." "Expected one of: ",
                    "(usb, str path like '/dev/ttyUSB0')",
                    "(bluetooth, str name like 'MESH_1111' or MAC like 'AA:BB:CC:DD:EE:FF')",
                    "(host, str like 'hostname:port' or 'hostname' for default port)",
                )

            # Retrieve local device information from the connected radio
            self.node_info = self.interface.getMyNodeInfo()

            # Extract this node's unique identifier from device info
            self.node_id = self.node_info.get("user", {}).get("id", "")

            # Node ID is required for communication validation
            if not self.node_id:
                logger.error("No node ID found")
                raise ValueError("No node ID found")
            logger.info(f"Connected to Meshtastic node: {self.node_id}")
        except Exception as e:
            logger.error(f"Failed to initialize Meshtastic interface (type: {connection_type}, path: {interface_path}): {e}")
            raise

        # Dictionary mapping request paths to handler functions and their response types
        self.routes = {}
        logger.debug(f"Server initialized with loop_interval={loop_interval}s, timeout={timeout}s, courtesy_interval={courtousy_interval}s")
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
        # Response type of current message: HTML (binary) or TEXT (plaintext)
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
        status_code: int = StatusCodes.SUCCESS,
    ) -> Iterator[ResponsePacket]:
        """
        Chunk a payload into transmission-sized packets.

        Splits payload respecting maximum packet size limits while generating ResponsePacket
        objects with appropriate chunk metadata. Handles both successful responses (status 200)
        and error responses separately.

        Parameters:
            payload (str | bytes): The response payload to chunk (HTML, text, or compressed bytes).
            status_code (int): HTTP status code (SUCCESS for success, other values for errors). Defaults to SUCCESS.

        Yields:
            ResponsePacket: Response packets ready for transmission, one chunk per iteration.

        Raises:
            ValueError: If payload exceeds maximum chunk count (255 chunks).
        """
        # Calculate safe payload size: reserve space for packet header and metadata
        payload_length = DATA_PAYLOAD_LEN - BUFFER_OFFSET
        logger.debug(f"Calculating chunks: payload_length={payload_length}, buffer_offset={BUFFER_OFFSET}")

        # Error responses are always sent as single chunk (not split across multiple packets)
        if status_code not in CHUNKABLE_STATUS_CODES:
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
            logger.error(f"Payload too large: requires {total_chunks} chunks, max is 255. Sending error response.")
            total_chunks = 1
            status_code = StatusCodes.INTERNAL_SERVER_ERROR
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
            response_type (str): Response format - HTML or TEXT. Determines compression and formatting.
            status_code (int): HTTP status code (200 for success, 4xx/5xx for errors).
            destination_id (str): Target node ID to send response to.

        Returns:
            None

        Raises:
            ValueError: If response_type is not HTML or TEXT.
        """
        logger.info(f"Sending response to {destination_id}: status={status_code}, type={response_type}")
        if response_type == ReturnTypes.HTML:
            # Remove unnecessary whitespace and HTML comments from the response to reduce size
            response_string = minify_html_onepass.minify(response_string)
            logger.debug(f"Minified response size: {len(response_string)} characters")

            # Apply Brotli compression with quality 11 (maximum compression) for further size reduction
            compressed_response_string = compress_payload(response_string)
            logger.debug(f"Compressed response size: {len(compressed_response_string)} bytes")

            for response_packet in self._get_chunks(compressed_response_string, status_code=status_code):
                # Encode the response packet into a byte sequence
                chunk = encode_packet(response_packet)
                logger.debug(f"Sending HTML response chunk {response_packet.current_chunk_id}/{response_packet.total_chunks} to {destination_id}")

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
                backoff_delay = self.air_traffic_control.apply_backoff_delay()
                if backoff_delay > 0.0:
                    logger.info(f"Channel congestion: applied {backoff_delay:.2f}s backoff delay before sending HTML chunk to {destination_id}")

                # Send the encoded packet to the destination node with acknowledgment request
                self.interface.sendData(chunk, destinationId=destination_id, wantAck=self.message_ack)
                logger.debug(f"Transmitted HTML chunk {response_packet.current_chunk_id}/{response_packet.total_chunks}")

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
                if status_code not in CHUNKABLE_STATUS_CODES:
                    return

                # Courtesy delay between chunks to give receiver time to process
                time.sleep(self.courtousy_interval)
        elif response_type == ReturnTypes.TEXT:
            # Send plain text responses as a sequence of TEXT_MESSAGE packets, one per chunk
            for response_packet in self._get_chunks(response_string, status_code=status_code):
                # Get the current chunk of the response
                chunk = response_packet.content
                logger.debug(f"Sending text response chunk {response_packet.current_chunk_id}/{response_packet.total_chunks} to {destination_id}")

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
                backoff_delay = self.air_traffic_control.apply_backoff_delay()
                if backoff_delay > 0.0:
                    logger.info(f"Channel congestion: applied {backoff_delay:.2f}s backoff delay before sending text chunk to {destination_id}")

                # Send the text message to the destination node with acknowledgment request
                self.interface.sendText(chunk, destinationId=destination_id, wantAck=self.message_ack)
                logger.debug(f"Transmitted text chunk {response_packet.current_chunk_id}/{response_packet.total_chunks}")

                # Wait for ACK (sets current_send_status and signals event when received or timed out)
                if self.message_ack:
                    self.response_event.wait(self.response_event_timeout)

                # Check ACK result: if failed/timed out after retries, abort remaining chunks
                if self.message_ack and not self.current_send_status:
                    logger.warning(f"Stopping transmission to {destination_id}: client unreachable or timed out")
                    self._reset_client_state()
                    return

                # Record packet transmission for air traffic control tracking
                self.air_traffic_control.add_packet_sent(len(response_packet.content))
                logger.debug(f"Text response chunk recorded for air traffic control ({len(response_packet.content)} bytes)")

                # Stop sending further chunks if error status (error responses are single-chunk only)
                if status_code not in CHUNKABLE_STATUS_CODES:
                    return

                # Courtesy delay between chunks to give receiver time to process
                time.sleep(self.courtousy_interval)
        else:
            logger.error(f"Invalid response type: {response_type}. Must be one of: {INTENDED_RETURN_TYPES}")
            raise ValueError(f"Invalid response type: {response_type}. Must be one of: {INTENDED_RETURN_TYPES}")

    def _throw_error_response(self, from_id: str, error_message: str, status_code: int, intended_return_type: str = ReturnTypes.TEXT) -> None:
        """
        Queue an error response to be sent back to a client.

        Creates a User object with error details and queues it for transmission.
        Error responses are typically sent as plain text, but may be HTML when the
        error message requires formatted content for complete client-side rendering
        (e.g., route listings, detailed error pages).

        Parameters:
            from_id (str): The client's node ID to send the error to.
            error_message (str): The error message content to send.
            status_code (int): HTTP status code (e.g., 400, 404, 500).
            intended_return_type (str): Response format - TEXT or HTML. Defaults to TEXT.

        Returns:
            None
        """
        logger.debug(f"Queuing error response to {from_id}: status={status_code}")
        self.user_queue.put(
            User(
                from_id=from_id,
                result=error_message,
                intended_return_type=intended_return_type,
                status_code=status_code,
                time_received=time.time(),
            )
        )

    def _on_receive(
        self,
        packet,
        interface: meshtastic.stream_interface.StreamInterface,
    ) -> None:
        """
        Handle incoming requests from mesh clients.

        Callback invoked by the Meshtastic pubsub system for each received packet.
        Extracts route requests, validates them against registered endpoints, and
        queues responses for processing. Automatically sends 404 errors for unknown routes.

        Parameters:
            packet (dict): The received Meshtastic packet containing decoded message data.
            interface (meshtastic.stream_interface.StreamInterface): The radio interface reference.

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
                logger.warning("Packet received without sender ID")
                return

            # Extract the receiver's node ID
            to_id = packet.get("toId", "")
            if to_id == "^all":
                # Ignore public channel messages (^all). We only process direct/private messages
                # to prevent channel saturation and avoid responding to normal conversations
                logger.warning("Ignoring public channel message")
                return

            # Perform the retry logic for the current client if needed
            if portnum == ROUTING_APP and from_id == self.current_client_node_id:
                logger.debug(f"Received routing message from {from_id}")
                # Get the routing metadata from the decoded message
                routing = decoded_message.get("routing", {})
                # Get the error reason from the routing metadata
                error_reason = routing.get("errorReason", None)
                # Convert the error reason to None if it is "NONE"
                error_reason = None if error_reason == "NONE" else error_reason
                logger.debug(f"Routing error reason from {from_id}: {error_reason}")

                # Determine retry logic: error_reason present means transmission failed at client
                if error_reason and self.current_event_retries < self.event_retries:
                    # Client reported an error and we haven't exceeded max retries
                    if self.current_client_message and self.response_type:
                        logger.info(f"Retrying message to {self.current_client_node_id} (attempt {self.current_event_retries + 1}/{self.event_retries}), error: {error_reason}")
                        # Resend the cached chunk using the same method (sendData for html, sendText for text)
                        if self.response_type == ReturnTypes.HTML:
                            self.interface.sendData(self.current_client_message, destinationId=self.current_client_node_id, wantAck=self.message_ack)
                        elif self.response_type == ReturnTypes.TEXT:
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
                    logger.debug(f"Received successful ACK from {from_id}")
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

            message_request_type = None

            try:
                # Attempt to decode as a binary packet (indicates web client request)
                decoded_packet = decode_packet(text)
                decompressed_payload = decompress_payload(decoded_packet.content)
                if decompressed_payload:
                    # Successfully decoded and decompressed: this is a web client request
                    text = decompressed_payload
                    message_request_type = ReturnTypes.HTML
                    logger.debug(f"Successfully decoded HTML request from {from_id}")
                else:
                    # Decoded but decompressed to empty: treat as text fallback
                    logger.debug(f"Empty decompressed payload from {from_id}, treating as text fallback")
                    message_request_type = ReturnTypes.TEXT
            except Exception as e:
                # Failed to decode as packet: this is a plain text request (Meshtastic app)
                logger.debug(f"Failed to decode as binary packet from {from_id} (expected for text requests): {type(e).__name__}")
                message_request_type = ReturnTypes.TEXT

            # Parse the incoming request into path and query parameters
            # Split on first "?" only to separate the endpoint path from query string
            # Using split("?", 1) instead of split("?") ensures that any "?" characters in query parameter values
            # (such as in LLM prompts or questions) are preserved (though they should ideally be URL-encoded as %3F)
            query_string = text.strip().split("?", 1)
            # Extract the path (everything before the "?")
            path = query_string[0].strip()
            # Extract and parse query parameters if they exist
            # If no query string present or it's empty/whitespace, default to empty dict
            request_parameters = parse_parameters(query_string[1].strip()) if len(query_string) > 1 and query_string[1].strip() else {}

            logger.debug(f"Query string split: path='{path}', has_query={len(query_string) > 1}, request_parameters={request_parameters}")
            logger.debug(f"Received request from {from_id}: type={message_request_type}, route={'<recognized>' if path in self.routes else '<not found>'}")

            # Check if the message is a valid endpoint
            if path and path in self.routes:
                # Log the parsed parameters for debugging
                logger.debug(f"Request parameters: {request_parameters}")

                # Get the function, intended return type, route parameters, and parameter types associated with the endpoint
                func = self.routes[path]["func"]
                intended_return_type = self.routes[path]["intended_return_type"]
                route_parameters = self.routes[path]["parameters"]
                parameter_types = self.routes[path]["parameter_types"]

                # Validate that the client type matches the endpoint's expected type
                # Send user-friendly error messages for common mismatches
                if message_request_type == ReturnTypes.TEXT and intended_return_type == ReturnTypes.HTML:
                    logger.info(f"Request mismatch from {from_id}: text client requesting HTML endpoint {path}")
                    self._throw_error_response(
                        from_id,
                        "This endpoint requires the MeshPages web client. Please use the web client instead of the Meshtastic app.",
                        StatusCodes.BAD_REQUEST,
                    )
                    return
                elif message_request_type == ReturnTypes.HTML and intended_return_type == ReturnTypes.TEXT:
                    logger.info(f"Request mismatch from {from_id}: HTML client requesting text endpoint {path}")
                    self._throw_error_response(
                        from_id,
                        "This endpoint requires the Meshtastic app. Please use the Meshtastic app instead of the MeshPages web client.",
                        StatusCodes.BAD_REQUEST,
                    )
                    return
                # Catch unexpected request types (edge case: malformed or hacked requests)
                elif message_request_type != intended_return_type and intended_return_type != ReturnTypes.BOTH:
                    logger.warning(f"Unexpected request type mismatch from {from_id}: request_type={message_request_type}, expected={intended_return_type}")
                    self._throw_error_response(
                        from_id,
                        f"Message request type {message_request_type} does not match intended return type {intended_return_type}",
                        StatusCodes.BAD_REQUEST,
                    )
                    return

                # Extract only the expected parameters from the incoming request
                # This filters out any extra/unknown parameters and sets missing parameters appropriately
                filtered_parameters = {}
                for parameter in route_parameters:
                    # Get the parameter type from the parameter types dictionary
                    parameter_type = parameter_types.get(parameter, str)

                    # Check if this parameter type is a MeshType
                    if isinstance(parameter_type, type) and issubclass(parameter_type, MeshType):
                        # MeshType parameters are generated from the packet, not from request
                        # Instantiate the MeshType and pass the instance
                        filtered_parameters[parameter] = parameter_type(packet)
                    elif parameter in request_parameters:
                        # Parameter was provided in the request: use the incoming value
                        filtered_parameters[parameter] = request_parameters[parameter]
                    else:
                        # Parameter was not provided: set to None so the function gets all expected params
                        filtered_parameters[parameter] = None

                try:
                    # Call the function associated with the endpoint with only expected parameters
                    result = func(**filtered_parameters)
                except Exception as e:
                    # Log the full error details for debugging and diagnostics
                    logger.error(f"Error calling function for {from_id} on {path}: {e}")
                    # Send generic error message to client (don't expose internal error details for security)
                    self._throw_error_response(
                        from_id,
                        "An error occurred processing your request. Please try again.",
                        StatusCodes.INTERNAL_SERVER_ERROR,
                    )
                    return

                # Set the status code to 200 on successful execution
                status_code = StatusCodes.SUCCESS

                # Add the user to the user queue
                self.user_queue.put(
                    User(
                        from_id=from_id,
                        result=result,
                        intended_return_type=message_request_type,
                        status_code=status_code,
                        time_received=time.time(),
                    )
                )
                logger.info(f"Request from {from_id} for {text} queued for response (status={status_code})")

                return
            else:
                # Route not found: compile list of available routes to suggest to the user
                logger.info(f"Route not found from {from_id}: requested {text}, available routes: {list(self.routes.keys())}")
                text_routes = []
                html_routes = []
                both_routes = []

                # Categorize routes by their intended return type with parameter type hints
                # Loop through all registered routes to format them with type information
                for route in self.routes:
                    # Get the route metadata (function, return type, parameters, etc.)
                    route_info = self.routes[route]
                    parameters = route_info.get("parameters", [])
                    parameter_types = route_info.get("parameter_types", {})

                    # Build query string example with type hints for documentation
                    if parameters:
                        query_parameters = []
                        # Build each parameter example showing its type (e.g., username=<str>)
                        for parameter in parameters:
                            # If the parameter is a MeshType, skip it because this is handled by the server and is not a direct user input
                            parameter_type = parameter_types.get(parameter, str)
                            if isinstance(parameter_type, type) and issubclass(parameter_type, MeshType):
                                continue
                            # Get the parameter's type, defaulting to str if no annotation exists
                            parameter_type_name = parameter_type.__name__
                            # Format as "parameter=<type>"
                            query_parameters.append(f"{parameter}=[{parameter_type_name}]")
                        # Construct the full route with query parameters only if there are user-facing parameters
                        if query_parameters:
                            route_with_params = f"{route}?{'&'.join(query_parameters)}"
                        # In the case of no user-facing parameters, use the route as-is
                        else:
                            route_with_params = route

                    else:
                        # Route has no parameters, use path as-is
                        route_with_params = route

                    # Categorize the formatted route by its intended return type
                    if route_info["intended_return_type"] == ReturnTypes.TEXT:
                        text_routes.append(route_with_params)
                    elif route_info["intended_return_type"] == ReturnTypes.HTML:
                        html_routes.append(route_with_params)
                    elif route_info["intended_return_type"] == ReturnTypes.BOTH:
                        both_routes.append(route_with_params)

                # Format routes as newline-separated lists for the error message
                text_routes_str = "Meshtastic App:\n" + "\n".join(text_routes)
                html_routes_str = "MeshPages Web Client:\n" + "\n".join(html_routes)
                both_routes_str = "All Clients:\n" + "\n".join(both_routes)

                # Return a 404 error with helpful suggestions about available routes (text routes for Meshtastic App, html routes for MeshPages Web Client)
                # Build error message with available routes, organized by client type
                route_error_message = "Invalid. Choose from the following routes:"
                if text_routes:
                    route_error_message += f"\n{text_routes_str}"
                if html_routes:
                    route_error_message += f"\n{html_routes_str}"
                if both_routes:
                    route_error_message += f"\n{both_routes_str}"
                # Format as styled HTML for web clients, plain text for Meshtastic app
                route_error_message = f"<pre style='color: orange; white-space: pre-wrap; word-wrap: break-word; font-family: monospace;'>{route_error_message}</pre>" if message_request_type == ReturnTypes.HTML else route_error_message

                self._throw_error_response(
                    from_id,
                    route_error_message,
                    StatusCodes.NOT_FOUND,
                    message_request_type,
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
            logger.debug(f"Processing queued request from {user.from_id}, queue size now: {self.user_queue.qsize()}")
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
                logger.error(f"Error processing user queue for {user.from_id}: {e}")
                pass
            finally:
                # Mark the task as complete (required for Queue.join() to work properly)
                self.user_queue.task_done()

    def page(
        self,
        path: str,
        intended_return_type: str = ReturnTypes.BOTH,
    ) -> Callable[[Callable], Callable]:
        """
        Decorator to register an endpoint handler for a GET-like request path.

        Usage:
            @server.page("/index.html", intended_return_type=ReturnTypes.HTML)
            def handle_index():
                return "<html>...</html>"

        Parameters:
            path (str): The request path to match (e.g., "/index.html" or "/status").
            intended_return_type (str): Response format - HTML, TEXT, or BOTH. Defaults to BOTH.

        Returns:
            Callable[[Callable], Callable]: Decorator function that registers the handler and returns it unchanged.

        Raises:
            ValueError: If intended_return_type is not HTML, TEXT, or BOTH.
        """

        # Validate the response type before registering the handler
        if intended_return_type not in INTENDED_RETURN_TYPES:
            logger.error(f"Invalid intended return type: {intended_return_type}. Must be one of: {INTENDED_RETURN_TYPES}")
            raise ValueError(f"Invalid intended return type: {intended_return_type}. Must be one of: {INTENDED_RETURN_TYPES}")

        # Define the inner decorator function that performs the registration
        def decorator(func: Callable):
            # Check if this endpoint is already registered
            if path in self.routes:
                raise ValueError(f"Endpoint '{path}' is already registered with return type '{self.routes[path]['intended_return_type']}'. Cannot register the same endpoint twice, even with different return types.")

            # Get the signature of the function
            signature = inspect.signature(func)

            # Get the parameters of the function with their type annotations
            # If no type annotation exists, default to str
            parameters_with_types = {}
            for param_name, param in signature.parameters.items():
                if param.annotation == inspect.Parameter.empty:
                    parameters_with_types[param_name] = str
                else:
                    parameters_with_types[param_name] = param.annotation

            parameter_names = list(parameters_with_types.keys())
            logger.debug(f"Registering route: {path} (returns {intended_return_type}) with parameters: {parameters_with_types}")

            # Store the handler function and its response type and parameters in the routes dictionary
            self.routes[path] = {
                "func": func,
                "intended_return_type": intended_return_type,
                "parameters": parameter_names,
                "parameter_types": parameters_with_types,
            }
            return func

        logger.info(f"Route registered: {path} -> {intended_return_type}")
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

            # Validate that at least one endpoint is registered before starting the server
            if not self.routes:
                raise ValueError("No routes registered. Please register at least one route using the @page decorator.")

            logger.info(f"Server started with {len(self.routes)} routes registered")
            logger.info("Server ready and listening for requests")

            # Main server loop: continuously process incoming requests and outgoing responses
            while True:
                # Wake up periodically to process queued responses
                time.sleep(self.loop_interval)

                # Send all queued responses to their destination clients
                self._process_user_queue()
        except KeyboardInterrupt:
            logger.info("Server interrupted by user")
            logger.info("Shutting down...")
            self.interface.close()
        except Exception as e:
            logger.error(f"Fatal error in server: {e}")
            logger.info("Shutting down...")
            self.interface.close()

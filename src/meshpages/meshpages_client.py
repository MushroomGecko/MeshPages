import logging
import os
import threading
from typing import Literal

import meshtastic
import meshtastic.ble_interface
import meshtastic.serial_interface
import meshtastic.stream_interface
import meshtastic.tcp_interface
from pubsub import pub

from meshpages.models import ResponsePacket
from meshpages.utils import compress_payload, decode_packet, decompress_payload, encode_packet, get_node_db_info, parse_hostname

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    # Allow environment variable to override log level (default: INFO)
    log_level = os.environ.get("PYTHONLOGLEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, log_level))

# Meshtastic portnum for binary data transmission (used for encoded packets)
PRIVATE_APP = "PRIVATE_APP"
# Meshtastic portnum for text messages (used for plain text responses)
TEXT_MESSAGE_APP = "TEXT_MESSAGE_APP"
# Meshtastic portnum for mesh routing information
ROUTING_APP = "ROUTING_APP"

# Supported content types for responses from remote nodes
INTENDED_RETURN_TYPES = ["html", "text"]


class MeshPagesClient:
    """
    Client for requesting web pages from nodes in a Meshtastic mesh network.

    Manages communication with remote mesh nodes over radio, handling multi-packet
    responses with compression and error handling. Uses air traffic control to
    regulate transmission rates on the shared mesh channel.
    """

    def __init__(
        self,
        connection_type: Literal["usb", "bluetooth", "host"] = "usb",
        interface_path: str = None,  # Path for connection: device path for USB (e.g. /dev/ttyUSB0), device name/MAC for Bluetooth (e.g. MESH_1111 or AA:BB:CC:DD:EE:FF), or "hostname:port" for host
        timeout: int = 300,  # in seconds
    ):
        """
        Initialize the mesh page client and connect to the mesh network.

        Parameters:
            connection_type (str): The type of connection to use ("usb", "bluetooth", "host"). Defaults to "usb".
            interface_path (str, optional): The path to the interface to use. Defaults to None (auto-detect).
                For USB: device path (e.g., '/dev/ttyUSB0')
                For Bluetooth: device name (e.g., 'MESH_1111') or MAC address (e.g., 'AA:BB:CC:DD:EE:FF')
                For host: "hostname:port" format (e.g., '192.168.1.100:4403')
            timeout (int): Maximum time in seconds to wait for a response from a remote node. Defaults to 300.

        Raises:
            ValueError: If no valid node ID is found on the connected Meshtastic device.
            Exception: If connection to the Meshtastic interface fails.
        """
        # Dictionary to buffer incoming packet chunks, keyed by chunk ID
        self.response_container: dict[int, bytes] = {}
        # Final decompressed text response (HTML or plain text)
        self.payload_string = ""
        # Raw compressed bytes from all assembled chunks
        self.payload_bytes = b""
        # Target node ID we're waiting for a response from (None if idle)
        self.target_node = None
        # Threading event to signal when the complete response is received
        self.response_event = threading.Event()
        # Maximum time in seconds to wait for response before timeout
        self.timeout = timeout
        # Total number of chunks expected in the multi-packet response
        self.expected_total_chunks = 0
        # Subscribe to the Meshtastic pubsub system to receive all incoming packets
        pub.subscribe(self._on_receive, "meshtastic.receive")

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
            user = self.interface.getMyNodeInfo().get("user", {})
            # Extract this node's unique identifier from device info
            self.node_id = user.get("id", "")
            # Node ID is required for communication validation
            if not self.node_id:
                logger.error("No node ID found")
                raise ValueError("No node ID found")
            logger.info(f"Connected to Meshtastic node: {self.node_id}")
        except Exception as e:
            logger.error(f"Failed to initialize Meshtastic interface (type: {connection_type}, path: {interface_path}): {e}")
            raise

    def _validate_target_node(
        self,
        target_node: str,
    ) -> bool:
        """
        Validate that the target node is reachable and not the local node.

        Parameters:
            target_node (str): Node ID to validate (should include "!" prefix).

        Returns:
            bool: True if node is valid and reachable, False otherwise.
        """
        # Prevent sending requests to ourselves (communication would be invalid)
        if target_node == self.node_id:
            logger.debug(f"Target node {target_node} is the local node, rejecting self-request")
            return False
        # Check if the target node appears in our neighbor list (is reachable)
        is_reachable = target_node in self.interface.nodes
        logger.debug(f"Checking target node {target_node}: reachable={is_reachable}")
        return is_reachable

    def _reset_state(self) -> None:
        """
        Reset the client's receive state after completing a request-response cycle.

        Clears buffered packets, chunk tracking, and in-flight receive state.
        Note: Does not clear payload_string as error handlers need it before calling this.

        Parameters:
            None

        Returns:
            None
        """
        # Clear in-flight receive state only. Do not clear payload_string here — error handlers
        # assign it just before calling this, then signal the waiter.
        self.target_node = None
        self.response_container = {}
        self.expected_total_chunks = 0
        self.payload_bytes = b""

    def _handle_error_response(
        self,
        response_packet: ResponsePacket | str | None,
    ) -> str | None:
        """
        Handle error responses and update client state accordingly.

        Parameters:
            response_packet (ResponsePacket | str | None): The response to process. Can be a ResponsePacket
                with error status code, a string error message, or None for unknown errors.

        Returns:
            str | None: Formatted HTML error message if error detected, None otherwise.

        Updates client state by setting payload_string, resetting receive state, and signaling waiting threads.
        """
        # Handle case where we received no packet at all (timeout or protocol failure)
        if not response_packet:
            logger.warning("No response packet received - returning generic error")
            error_message = "<div style='color: orange;'>An unknown error occurred.</div>"
            self.payload_string = error_message
            self._reset_state()
            self.response_event.set()
            return error_message

        # Handle text error messages (usually from TEXT_MESSAGE_APP)
        if isinstance(response_packet, str):
            logger.info(f"Received text error response: {response_packet[:100]}")
            # Wrap in <pre> tag to preserve newlines and whitespace from server
            formatted_message = f"<pre style='color: orange; white-space: pre-wrap; word-wrap: break-word; font-family: monospace;'>{response_packet}</pre>"
            self.payload_string = formatted_message
            self._reset_state()
            self.response_event.set()
            return formatted_message

        # Handle ResponsePacket with non-200 status code (error response from server)
        if isinstance(response_packet, ResponsePacket) and response_packet.status_code != 200:
            # Status code responses include plain text error messages (not compressed)
            response_packet_content = response_packet.content if isinstance(response_packet.content, str) else response_packet.content.decode("utf-8")
            logger.info(f"Received error response from server: status={response_packet.status_code}")
            # Wrap in <pre> tag to preserve newlines and whitespace from server
            error_message = f"<pre style='color: orange; white-space: pre-wrap; word-wrap: break-word; font-family: monospace;'>Error Code: {response_packet.status_code}\n{response_packet_content}</pre>"
            self.payload_string = error_message
            self._reset_state()
            self.response_event.set()
            return error_message

        # No error detected - return None to indicate success
        return None

    def _on_receive(
        self,
        packet,
        interface: meshtastic.stream_interface.StreamInterface,
    ) -> None:
        """
        Handle incoming radio packets from the Meshtastic interface.

        This callback is invoked by the pubsub system for each received packet. It handles
        multi-packet responses by buffering chunks until all are received, then decompresses
        and signals the waiting request thread.

        Parameters:
            packet (dict): The received Meshtastic packet containing decoded data.
            interface (meshtastic.stream_interface.StreamInterface): The radio interface reference.

        Returns:
            None

        Processes packets based on portnum (PRIVATE_APP for data, TEXT_MESSAGE_APP for text).
        Handles partial chunks, error responses, and timeouts gracefully.
        """
        # Ignore packets if we're not currently waiting for a response (no active request)
        if not self.target_node:
            logger.debug(f"Ignoring message from {packet.get('fromId', 'Unknown')}: not waiting for response")
            return

        # Process the received packet and handle multi-chunk assembly
        try:
            decoded_message = packet.get("decoded", {})
            portnum = decoded_message.get("portnum", "")

            # Extract the receiver's node ID
            to_id = packet.get("toId", "")
            if to_id != self.node_id:
                # Ignore messages not addressed to this node. The client only processes direct messages
                # intended for it. This filters out public channel messages (^all) and messages to other nodes.
                logger.warning(f"Ignoring message addressed to {to_id}, not our node {self.node_id}")
                return

            # Extract the sender's node ID
            from_id = packet.get("fromId", "")
            if portnum == PRIVATE_APP and from_id == self.target_node and to_id == self.node_id:
                # Decode the binary packet into a ResponsePacket structure
                response_packet = decode_packet(decoded_message.get("payload", b""))
                logger.debug(f"Received PRIVATE_APP chunk from {from_id}: chunk {response_packet.current_chunk_id if response_packet else '?'}/{response_packet.total_chunks if response_packet else '?'}")

                # Immediate error response: status code indicates server error, decompress and return
                if response_packet and response_packet.status_code != 200:
                    logger.info(f"Received error response from {from_id}: status={response_packet.status_code}")
                    self.payload_string = decompress_payload(response_packet.content)
                    self._reset_state()
                    self.response_event.set()
                    return

                # On first chunk: record total chunk count for this response
                if response_packet and not self.expected_total_chunks:
                    self.expected_total_chunks = response_packet.total_chunks
                    logger.debug(f"Expecting {self.expected_total_chunks} total chunks from {from_id}")

                # Intermediate chunk: buffer it and wait for more (unless it's the last chunk)
                if response_packet and self.expected_total_chunks and response_packet.current_chunk_id != self.expected_total_chunks:
                    # Store this chunk in the buffer (chunk IDs are 1-indexed)
                    self.response_container[response_packet.current_chunk_id] = response_packet.content
                    logger.debug(f"Buffered chunk {response_packet.current_chunk_id}/{self.expected_total_chunks}, waiting for more...")
                    return

                # Final chunk received: assemble all chunks, decompress, and signal completion
                elif response_packet and self.expected_total_chunks and response_packet.current_chunk_id == self.expected_total_chunks:
                    # Store the final chunk
                    self.response_container[response_packet.current_chunk_id] = response_packet.content
                    logger.debug(f"Received final chunk {response_packet.current_chunk_id}/{self.expected_total_chunks}, assembling response...")

                    # TODO: Improve multi-chunk reassembly robustness:
                    #   - Validate all chunk IDs 1..N are present before joining (currently crashes if chunk missing)
                    #   - Verify each packet's total_chunks matches the first packet
                    #   - Fail explicitly with error payload instead of relying on timeout/decompression to catch issues

                    # Reassemble all chunks in order (no sorting needed since we iterate by chunk ID)
                    for chunk_id in range(1, self.expected_total_chunks + 1):
                        self.payload_bytes += self.response_container[chunk_id]
                    # Decompress the complete payload
                    self.payload_string = decompress_payload(self.payload_bytes)
                    logger.info(f"Successfully received complete response from {from_id}: {len(self.payload_string)} characters")

                    # Reset state and signal the waiting thread that response is complete
                    self._reset_state()
                    self.response_event.set()
                    return

                # Unexpected state: missing packet, invalid chunk ID, or malformed response
                else:
                    if not response_packet:
                        logger.error("Failed to decode response packet")
                    if not self.expected_total_chunks:
                        logger.error("No expected total chunks set")
                    logger.error(f"Unexpected response state from {from_id}: packet={response_packet}, expected_total={self.expected_total_chunks}")
                    return
            elif portnum == TEXT_MESSAGE_APP and from_id == self.target_node and to_id == self.node_id:
                # TEXT_MESSAGE_APP responses are plain text error messages (not multi-chunk)
                message = decoded_message.get("text", "")
                logger.debug(f"Received TEXT_MESSAGE_APP from {from_id}")
                self._handle_error_response(message if message else None)
                return
            elif from_id == self.target_node and to_id == self.node_id:
                # Message from target but wrong portnum
                logger.debug(f"Received message from target {from_id} with unexpected portnum: {portnum}")
                return
            else:
                # Message addressed to this node but from unexpected source or invalid combination
                logger.debug(f"Ignoring unexpected message from {from_id} to {to_id} with portnum {portnum}")
                return
        except Exception as e:
            logger.error(f"Error processing received message from {packet.get('fromId', 'Unknown')}: {e}")
            self._handle_error_response(None)
            return

    def request_page(
        self,
        target_node: str,
        path: str,
    ) -> str:
        """
        Request a web page from a remote mesh node and wait for the response.

        This is the main public interface that bridges the web server with mesh radio communication.
        Sends a text request to the target node, waits for multi-packet response, and returns
        decompressed content or an error message.

        Parameters:
            target_node (str): The target node ID (with or without "!" prefix).
            path (str): The resource path to request (e.g., "/index.html").

        Returns:
            str: The HTML/text response from the remote node, or an HTML-formatted error message
                 if validation, timeout, or processing fails.
        """
        # Normalize node ID to include Meshtastic's required "!" prefix for addressing
        node_id = target_node if target_node.startswith("!") else f"!{target_node}"

        # Validate target node exists and is reachable in the mesh network
        if not self._validate_target_node(node_id):
            # Target node not found; check for special case of self-request
            if node_id == self.node_id:
                logger.info(f"Rejected self-request for {path}")
                return "<div style='color: orange;'>You cannot request a page from yourself.</div>"

            # Build user-friendly error message with available nodes for reference
            available_nodes = get_node_db_info(self.interface)
            logger.info(f"Target node {node_id} not reachable. Available nodes: {list(available_nodes.keys())}")
            html_return_string = f"<div style='color: orange;'>Invalid target node: {node_id}. Available nodes:<ul>"

            # Format each available node with identification and local node indicator
            for node in available_nodes:
                local_indicator = "<span style='color: green;'><-- You</span>" if available_nodes[node]["isMyNode"] else ""
                html_return_string += f"<li>{node}: {available_nodes[node]['longName']} ({available_nodes[node]['shortName']}) {local_indicator}</li>"

            html_return_string += "</ul></div>"
            return html_return_string

        logger.info(f"Requesting {path} from {node_id}")

        # Initialize state for this request: clear previous response data and set new target
        self.target_node = node_id
        self.response_container = {}
        self.payload_string = ""
        self.payload_bytes = b""
        self.expected_total_chunks = 0
        self.response_event.clear()

        compressed_payload = compress_payload(path)
        encoded_payload = encode_packet(
            ResponsePacket(
                current_chunk_id=1,
                total_chunks=1,
                status_code=200,
                content=compressed_payload,
            )
        )

        # Send the page request to the target node (as a binary message)
        logger.debug(f"Sending page request ({len(encoded_payload)} bytes) to {node_id}")
        self.interface.sendData(
            encoded_payload,
            destinationId=node_id,
        )

        # Block and wait for the complete response with timeout protection
        # Note: Event.wait() expects timeout in seconds
        response = self.response_event.wait(self.timeout)

        if response:
            # Response completed successfully: return the decompressed content
            logger.info(f"Successfully retrieved response from {node_id}")
            return self.payload_string
        else:
            # Timeout waiting for response: return user-friendly error message
            logger.warning(f"Timeout: {node_id} didn't reply within {self.timeout} seconds for path {path}")
            return f"<div style='color: orange;'>Timeout: {node_id} didn't reply.</div>"

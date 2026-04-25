import brotli
from urllib.parse import parse_qsl

import meshtastic
import meshtastic.ble_interface
import meshtastic.stream_interface

from meshpages.enums import StatusCodes
from meshpages.models import ResponsePacket

# Status codes that support chunked/multi-packet responses
CHUNKABLE_STATUS_CODES = [StatusCodes.SUCCESS, StatusCodes.NOT_FOUND]


def parse_uri(uri: str) -> tuple[str, str]:
    """
    Parse a mesh URI into node ID and path components.

    Parameters:
        uri (str): URI in the format 'mesh://<node_id>/<path>'.

    Returns:
        tuple[str, str]: A tuple containing (node_id, path). Returns (None, None) if URI is invalid.
    """
    if uri.startswith("mesh://"):
        # Extract everything after the "mesh://" prefix and split by "/" to separate node_id from path
        parts = uri.split("://")[1].split("/")

        # Edge case: URI like "mesh://node123" with no trailing slash means root path
        if len(parts) == 1:
            return (parts[0], "/")

        # Reconstruct the path from remaining parts and ensure it starts with "/"
        combined_path = "/".join(parts[1:])
        if not combined_path.startswith("/"):
            combined_path = "/" + combined_path
        return (parts[0], combined_path)
    else:
        # Invalid URI format - return None tuple to indicate parsing failure
        return (None, None)


def parse_parameters(query_string: str) -> dict:
    """
    Parse a query string into a dictionary of parameters.

    Extracts and decodes query string parameters into a key-value dictionary.
    Handles URL decoding automatically (e.g., '+' to space, '%XX' hex codes).
    Accepts query strings with or without the leading '?' character.

    Parameters:
        query_string (str): Query string in format 'key1=value1&key2=value2' or '?key1=value1&key2=value2'.

    Returns:
        dict: Dictionary of parsed parameters, or empty dict if query string is empty.
    """
    # Return empty dict if query string is empty or None
    if not query_string:
        return {}

    # Remove leading "?" if present
    if query_string.startswith("?"):
        query_string = query_string[1:]

    # parse_qsl automatically handles URL decoding and returns list of (key, value) tuples
    # dict() converts tuples to dictionary
    return dict(parse_qsl(query_string))


def parse_hostname(hostname: str) -> tuple[str, int]:
    """
    Parse a hostname string into a tuple of (hostname, port).

    Parses "hostname:port" format. If no port is specified, defaults to 4403 (Meshtastic TCP default).

    Parameters:
        hostname (str): Hostname string in format "hostname:port" or just "hostname".

    Returns:
        tuple[str, int]: A tuple containing (hostname, port).

    Raises:
        ValueError: If the port is not a valid integer.
    """
    if ":" in hostname:
        parts = hostname.split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid hostname format: {hostname}. Expected 'hostname:port' or 'hostname'")
        try:
            port = int(parts[1].strip())
            return (parts[0].strip(), port)
        except ValueError as e:
            raise ValueError(f"Invalid port in hostname: {parts[1]} is not a valid integer") from e
    else:
        # Default to Meshtastic TCP default port if not specified
        return (hostname.strip(), 4403)


def compress_payload(payload: str) -> bytes:
    """
    Compress a payload string using Brotli compression.

    Parameters:
        payload (str): The string payload to compress.

    Returns:
        bytes: Compressed bytes, or empty bytes if compression fails.
    """
    try:
        # Brotli compression is highly efficient for text/structured data
        # Quality 11 provides maximum compression at the cost of slower compression speed
        # This is acceptable for offline compression scenarios
        return brotli.compress(payload.encode("utf-8"), quality=11)
    except Exception:
        # Log compression errors but return empty bytes to allow graceful degradation
        return b""


def decompress_payload(payload: bytes) -> str:
    """
    Decompress a Brotli-compressed payload to a string.

    Parameters:
        payload (bytes): The compressed bytes to decompress.

    Returns:
        str: The decompressed string, or empty string if decompression fails.
    """
    try:
        # Decompress the Brotli-compressed data and decode back to UTF-8 string
        return brotli.decompress(payload).decode("utf-8")
    except Exception:
        # Log decompression errors but return empty string to allow graceful degradation
        return ""


def encode_packet(response_packet: ResponsePacket) -> bytes:
    """
    Encode a ResponsePacket into a byte sequence.

    Converts a ResponsePacket object into the binary format used for mesh transmission:

    Packet Format Example: "6301C8GODNFMDGOMPFKQVPG..."
    Structure breakdown:
      - 63 = Total chunks in response (hex: 2 chars, max value 255)
      - 01 = Current chunk ID (hex: 2 chars, 1-indexed, max 255)
      - C8G = HTTP status code (hex: 3 chars, max value 4095, supports all standard codes)
      - ODNFMDGOMPFKQVPG... = Brotli-compressed content (variable length)

    Parameters:
        response_packet (ResponsePacket): The packet to encode.

    Returns:
        bytes: Encoded packet with header (chunk ID, total chunks, status code) followed by content.
    """
    # Packet structure: [2-byte chunk_id][2-byte total_chunks][3-byte status_code][content]
    # Each value is encoded as uppercase hexadecimal string for binary serialization

    # Current chunk ID: 2 hex chars = 8 bits = supports chunks 0-255
    hex_current_chunk_id = format(response_packet.current_chunk_id, "02X")
    # Total number of chunks: 2 hex chars = 8 bits = supports up to 255 chunks per response
    hex_total_chunks = format(response_packet.total_chunks, "02X")
    # HTTP status code: 3 hex chars = 12 bits = supports codes up to 4095 (covers all standard HTTP codes and extensions)
    hex_status_code = format(response_packet.status_code, "03X")

    # Combine header fields into a single hex string and encode to UTF-8 bytes
    hex_bytes = f"{hex_current_chunk_id}{hex_total_chunks}{hex_status_code}".encode("utf-8")
    # Prepend header to the packet content (content is already Brotli-compressed)
    combined_bytes = hex_bytes + response_packet.content
    return combined_bytes


def decode_packet(payload: bytes) -> ResponsePacket:
    """
    Decode a byte sequence into a ResponsePacket.

    Parses the binary mesh packet format into a ResponsePacket object:

    Packet Format Example: "6301C8GODNFMDGOMPFKQVPG..."
    Structure breakdown:
      - 63 = Total chunks in response (hex: 2 chars, max value 255)
      - 01 = Current chunk ID (hex: 2 chars, 1-indexed, max 255)
      - C8G = HTTP status code (hex: 3 chars, max value 4095, supports all standard codes)
      - ODNFMDGOMPFKQVPG... = Brotli-compressed content (variable length)

    Parameters:
        payload (bytes): The encoded packet bytes to decode.

    Returns:
        ResponsePacket: Decoded packet object, or None if decoding fails.
    """
    try:
        # Packet structure: [2-byte chunk_id][2-byte total_chunks][3-byte status_code][content]
        # All header values are hex-encoded as UTF-8 strings

        # Extract and decode current chunk ID (bytes 0-1): 2 hex chars = 8 bits
        encoded_current_chunk_id = payload[0:2].decode("utf-8")
        decoded_current_chunk_id = int(encoded_current_chunk_id, 16)

        # Extract and decode total chunks (bytes 2-3): 2 hex chars = 8 bits
        encoded_total_chunks = payload[2:4].decode("utf-8")
        decoded_total_chunks = int(encoded_total_chunks, 16)

        # Extract and decode status code (bytes 4-6): 3 hex chars = 12 bits
        encoded_status_code = payload[4:7].decode("utf-8")
        decoded_status_code = int(encoded_status_code, 16)

        # Remaining bytes (from byte 7 onwards) contain the Brotli-compressed content
        compressed_content = payload[7:]

        return ResponsePacket(
            current_chunk_id=decoded_current_chunk_id,
            total_chunks=decoded_total_chunks,
            status_code=decoded_status_code,
            content=compressed_content,
        )
    except Exception:
        # Log decoding errors with details for debugging packet format issues
        return None


def get_node_db_info(interface: meshtastic.stream_interface.StreamInterface) -> dict:
    """
    Extract and format node information from the mesh network database.

    Queries the connected radio device for all nodes in its node database and
    extracts human-readable identification information. Includes identification
    of the local node for easier reference in display contexts.

    Parameters:
        interface (meshtastic.stream_interface.StreamInterface): Connected interface to the Meshtastic radio.

    Returns:
        dict: Dictionary keyed by node ID (int), each value contains:
            - longName (str): Full name of the node
            - shortName (str): Short identifier for the node
            - isMyNode (bool): True if this is the local radio node
    """
    # Retrieve the local node's information to identify which node is "mine"
    my_node_info = interface.getMyNodeInfo()
    my_node_id = my_node_info.get("user", {}).get("id", "")

    # Get all nodes currently stored in the device's node database
    all_nodes = interface.nodes
    node_db_info = {}

    # Extract relevant user information for each node
    for node in all_nodes:
        node_user = all_nodes[node].get("user", {})
        node_db_info[node] = {
            "longName": node_user.get("longName", ""),
            "shortName": node_user.get("shortName", ""),
            "isMyNode": True if my_node_id == node else False,
        }

    return node_db_info

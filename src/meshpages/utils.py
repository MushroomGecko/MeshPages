import logging

import brotli
import meshtastic
import meshtastic.serial_interface

from meshpages.models import ResponsePacket

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
    except Exception as e:
        # Log compression errors but return empty bytes to allow graceful degradation
        logger.error(f"Error compressing payload: {e}")
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
    except Exception as e:
        # Log decompression errors but return empty string to allow graceful degradation
        logger.error(f"Error decompressing payload: {e}")
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
    logger.debug(f"Encoded packet: {combined_bytes}")
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
        logger.debug(f"Current chunk ID: {decoded_current_chunk_id}")

        # Extract and decode total chunks (bytes 2-3): 2 hex chars = 8 bits
        encoded_total_chunks = payload[2:4].decode("utf-8")
        decoded_total_chunks = int(encoded_total_chunks, 16)
        logger.debug(f"Total chunks: {decoded_total_chunks}")

        # Extract and decode status code (bytes 4-6): 3 hex chars = 12 bits
        encoded_status_code = payload[4:7].decode("utf-8")
        decoded_status_code = int(encoded_status_code, 16)
        logger.debug(f"Status code: {decoded_status_code}")

        # Remaining bytes (from byte 7 onwards) contain the Brotli-compressed content
        compressed_content = payload[7:]
        logger.debug(f"Compressed content size: {len(compressed_content)} bytes")

        return ResponsePacket(
            current_chunk_id=decoded_current_chunk_id,
            total_chunks=decoded_total_chunks,
            status_code=decoded_status_code,
            content=compressed_content,
        )
    except Exception as e:
        # Log decoding errors with details for debugging packet format issues
        logger.error(f"Error decoding packet: {e}")
        return None


def get_node_db_info(interface: meshtastic.serial_interface.SerialInterface) -> dict:
    """
    Extract and format node information from the mesh network database.

    Queries the connected radio device for all nodes in its node database and
    extracts human-readable identification information. Includes identification
    of the local node for easier reference in display contexts.

    Parameters:
        interface (meshtastic.serial_interface.SerialInterface): Connected interface to the Meshtastic radio.

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

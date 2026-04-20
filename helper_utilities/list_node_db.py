"""
Utility to list nodes in the Meshtastic mesh network database.

This module retrieves and displays all nodes currently stored in the local
node database of a connected Meshtastic radio device. It provides node
identification information including long names, short names, and highlights
the local node.
"""

import argparse

import meshtastic
import meshtastic.serial_interface
import meshtastic.stream_interface

from meshpages.utils import get_node_db_info, parse_hostname

# Create CLI argument parser for specifying interface connection
parser = argparse.ArgumentParser(description="List nodes in the Meshtastic mesh network database")
parser.add_argument(
    "--interface-type",
    type=str,
    choices=["usb", "bluetooth", "host"],
    default="usb",
    help="Connection type for the radio (usb, bluetooth, or host). Defaults to usb.",
)
parser.add_argument(
    "--interface-path",
    type=str,
    default=None,
    help="Path for the connection: device path for USB/Bluetooth (e.g., /dev/ttyUSB0), or 'hostname:port' for host connections (e.g., 192.168.1.100:4403).",
)
args = parser.parse_args()


def list_node_db() -> None:
    """
    List all nodes in the local Meshtastic mesh network database.

    Connects to the radio device, retrieves all nodes stored in the node
    database, and displays them with their identification information. Each
    node's long name, short name, and local node indicator are printed.

    Raises:
        ValueError: If connection configuration is invalid.
        Exception: If unable to connect to the radio device.

    Returns:
        None
    """
    # Get connection parameters from CLI arguments
    connection_type = args.interface_type
    interface_path = args.interface_path

    # Connect to the radio device via the specified interface
    if connection_type == "usb":
        interface = meshtastic.serial_interface.SerialInterface(interface_path)
    elif connection_type == "bluetooth":
        interface = meshtastic.bluetooth_interface.BluetoothInterface(interface_path)
    elif connection_type == "host":
        if not interface_path:
            raise ValueError("Host connection requires interface_path in format 'hostname:port' or 'hostname' (defaults to port 4403)")
        hostname, port = parse_hostname(interface_path)
        interface = meshtastic.tcp_interface.TCPInterface(hostname, portNumber=port)
    else:
        raise ValueError(f"Invalid connection configuration. Got connection_type={connection_type!r}, interface_path={interface_path!r}. " f"Expected one of: " f"(usb, str path like '/dev/ttyUSB0'), " f"(bluetooth, str path like '/dev/rfcomm0'), " f"(host, str like 'hostname:port' or 'hostname' for default port)")

    # Retrieve the node database from the connected radio
    nodes = get_node_db_info(interface)

    # Handle empty node database
    if not nodes:
        print("No nodes found in the node database.")
        return None

    # Display all nodes with their information
    print("Nodes in the node database:")
    for node in nodes:
        local_indicator = "<-- You" if nodes[node]["isMyNode"] else ""
        print(f"- {node}: {nodes[node]['longName']} ({nodes[node]['shortName']}) {local_indicator}")


if __name__ == "__main__":
    list_node_db()

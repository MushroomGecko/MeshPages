"""
Utility to list nodes in the Meshtastic mesh network database.

This module retrieves and displays all nodes currently stored in the local
node database of a connected Meshtastic radio device. It provides node
identification information including long names, short names, and highlights
the local node.
"""

import meshtastic
import meshtastic.serial_interface
from meshpages.utils import get_node_db_info
import argparse

# Create CLI argument parser for specifying USB interface
parser = argparse.ArgumentParser(description="List nodes in the Meshtastic mesh network database")
parser.add_argument(
    "--usb-interface",
    type=str,
    default=None,
    help="USB interface for the radio connection (e.g., /dev/ttyUSB0). If not specified, uses default.",
)
args = parser.parse_args()


def list_node_db() -> None:
    """
    List all nodes in the local Meshtastic mesh network database.

    Connects to the radio device, retrieves all nodes stored in the node
    database, and displays them with their identification information. Each
    node's long name, short name, and local node indicator are printed.

    Raises:
        SerialException: If unable to connect to the radio device.

    Returns:
        None
    """
    # Get the USB interface from CLI arguments, defaulting to auto-detection
    usb_interface = None if not args.usb_interface else args.usb_interface

    # Connect to the radio device
    interface = meshtastic.serial_interface.SerialInterface(usb_interface)

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

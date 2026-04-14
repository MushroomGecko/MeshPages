"""
Utility to discover Meshtastic radio devices connected to the system.

This module provides a simple interface for finding USB-connected Meshtastic
radio devices, which is useful for identifying available interfaces before
connecting to the mesh network.
"""

import meshtastic.util


def find_radios() -> None:
    """
    Discover and list all connected Meshtastic radio devices.

    Queries the system for connected Meshtastic devices via USB and prints
    their device paths. If no devices are found, displays a helpful message
    about potential permission issues.

    Parameters:
        None

    Returns:
        None
    """
    # Query the system for connected Meshtastic devices (returns list of port paths)
    ports = meshtastic.util.findPorts()

    # Handle case where no devices are connected
    if not ports:
        print("No Meshtastic devices found. (Remember to use 'sudo' if you have permission issues!)")
        return None

    # Display discovered device ports
    print("Found Meshtastic devices on:")
    for port in ports:
        print(f"- {port}")


if __name__ == "__main__":
    find_radios()

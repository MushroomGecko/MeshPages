"""
Utility to discover Meshtastic radio devices connected to the system.

This module provides a simple interface for finding Meshtastic radio devices
via USB, Bluetooth, or other connection types available on the system.
"""

import logging

import meshtastic.util
import meshtastic.ble_interface

logging.basicConfig(level=logging.WARNING)


def _find_usb_devices() -> None:
    """
    Discover and display USB-connected Meshtastic devices.

    Queries the system for connected USB Meshtastic devices and prints their
    device paths. If no devices are found, displays an informational message.

    Returns:
        None
    """
    print("\n[USB Connections]")
    usb_ports = meshtastic.util.findPorts()
    if usb_ports:
        for port in usb_ports:
            print(f"  - {port}")
    else:
        print("  (No USB devices found)")


def _find_ble_devices() -> None:
    """
    Discover and display Bluetooth-connected Meshtastic devices.

    Scans for Meshtastic devices via Bluetooth Low Energy (BLE) and prints
    their names and MAC addresses. Includes error handling for scanning failures.

    Returns:
        None
    """
    print("\n[Bluetooth Connections]")
    try:
        ble_devices = meshtastic.ble_interface.BLEInterface.scan()
        if ble_devices:
            for device in ble_devices:
                device_name = device.name if hasattr(device, "name") and device.name else "Unknown"
                device_addr = device.address if hasattr(device, "address") else "Unknown"
                print(f"  - {device_name} ({device_addr})")
        else:
            print("  (No Bluetooth devices found)")
    except Exception as e:
        print(f"  (Error scanning for Bluetooth devices: {e})")


def _find_host_info() -> None:
    """
    Display information about host (TCP/Network) connections.

    Shows that automatic host device discovery is not yet available and
    provides guidance on manual configuration with hostname:port format.

    Returns:
        None
    """
    print("\n[Host Connections (TCP/Network)]")
    print("  (Device discovery not yet available - use hostname:port manually)")
    print("  (Example: 192.168.1.100:4403)")


def find_radios() -> None:
    """
    Discover and list all connected Meshtastic radio devices.

    Queries the system for connected Meshtastic devices via USB, Bluetooth,
    and displays information about host (TCP) connections. Results are
    organized by connection type for easy reference.

    Parameters:
        None

    Returns:
        None
    """
    print("=" * 60)
    print("Meshtastic Device Discovery")
    print("=" * 60)

    _find_usb_devices()
    _find_ble_devices()
    _find_host_info()


if __name__ == "__main__":
    find_radios()

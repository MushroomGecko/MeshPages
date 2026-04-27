from pathlib import Path

from meshpages import MeshPagesServer
from meshpages.enums import ChannelPresets
from meshpages.types import ClientID

# Get the directory where this script is located
script_dir = Path(__file__).parent

app = MeshPagesServer(
    connection_type="usb",  # Connection type: "usb", "bluetooth", or "host". Defaults to "usb".
    interface_path="/dev/ttyUSB0",  # USB: device path (e.g. /dev/ttyUSB0), Bluetooth: device name/MAC (MESH_1111 or AA:BB:CC:DD:EE:FF), Host: "hostname:port". Auto-detects if None.
    loop_interval=0.5,  # Run the main server loop every 0.5 seconds
    message_ack=False,  # Use UDP style of message sending (set to True for TCP style)
    courtousy_interval=3.0,  # Delay between sending consecutive chunks (in seconds). Default 3.0 seconds in order for any Meshtastic apps to be able to process all the chunks coming in.
    timeout=300,  # Maximum time to wait before dropping a client request (in seconds). Default 300 seconds.
    air_traffic_control_config=ChannelPresets.LONG_FAST,  # Use the LONG_FAST channel preset
    air_traffic_control_target_utilization_percent=50.0,  # Target channel utilization (in percent). Default 50%.
    air_traffic_control_window_seconds=10.0,  # Time window for utilization calculation (in seconds). Default 10 seconds.
    air_traffic_control_meshtastic_overhead_bytes=20,  # Protocol overhead per packet (in bytes) (probably doesn't need to be changed, but is explicitly set here for clarity and demonstration purposes)
)


print("Mesh Server Running...")

allowed_clients = [
    # "!a4c3b8f2",
    # "!7d9e2c51",
    # "!f3a7e0b9",
    # "!2c5d8a9b",
    # YOUR CLIENT ID HERE
]

correct_password = "password"


@app.page("/secret_html", intended_return_type="html")
def secret_html_page(client_id: ClientID, password: str):
    print("CLIENT ID: ", client_id)
    print("PASSWORD: ", password)

    if client_id not in allowed_clients:
        return f"Unauthorized: {client_id} is not in the allowed clients list. Whomp whomp."

    if password != correct_password:
        return "Unauthorized: The password is incorrect. Whomp whomp."

    with open(script_dir / "templates" / "home.html", "r") as file:
        return file.read()


@app.page("/secret_text", intended_return_type="text")
def secret_text_page(client_id: ClientID, password: str):
    print("CLIENT ID: ", client_id)
    print("PASSWORD: ", password)

    if client_id not in allowed_clients:
        return f"Unauthorized: {client_id} is not in the allowed clients list. Whomp whomp."

    if password != correct_password:
        return "Unauthorized: The password is incorrect. Whomp whomp."

    return "You've been Rickrolled! 🎵 Never gonna give you up. Never gonna let you down. 😎"


app.run()

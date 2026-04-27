from pathlib import Path

from ollama import Client

from meshpages import MeshPagesServer
from meshpages.enums import ChannelPresets

# Get the directory where this script is located
script_dir = Path(__file__).parent

MODEL = "qwen3.5:2b-q4_K_M"

# Initialize Ollama client
client = Client()

# Check if model exists, pull if not
try:
    models_response = client.list()
    model_names = [model.model for model in models_response.models]

    if MODEL not in model_names:
        print(f"Model {MODEL} not found, pulling...")
        client.pull(MODEL)
except Exception as e:
    print(f"Error checking/pulling model {MODEL}: {e}")
    raise

print(f"Model {MODEL} ready to use.")


def llm_text_response(prompt: str):
    system_prompt = """You are MeshBot, an AI assistant running on a MeshPages server - a FastAPI-style web server built on top of the Meshtastic mesh network. 

About your context:
- You're deployed on a low-bandwidth, long-range mesh network (LoRa-based)
- Responses should be concise and informative (mesh has limited bandwidth)
- You can provide technical information, answer questions, and have conversations
- Users are accessing you through a mesh-connected web client or the Meshtastic app
- Responses are transmitted over radio, so brevity and clarity are important

Guidelines:
- Keep responses short and to the point
- Use clear, plain language
- Avoid unnecessary formatting when possible
- Be helpful and direct
- If something requires extensive explanation, offer a summary with an invitation for follow-up questions"""

    response = client.chat(model=MODEL, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}], think=False)
    return response.message.content


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


@app.page("/llm_html", intended_return_type="html")
def llm_page_html(prompt: str):
    return llm_text_response(prompt)


@app.page("/llm_text", intended_return_type="text")
def llm_page_text(prompt: str):
    return llm_text_response(prompt)


app.run()

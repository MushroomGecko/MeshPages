# MeshPages

MeshPages enables web-based communication over Meshtastic mesh networks. It allows you to request and serve web pages directly over Meshtastic radios, turning your Meshtastic device into a wireless web server or client.

<img style="width: 50%; height: auto;" alt="MeshPages_Client_Screenshot" src="https://github.com/user-attachments/assets/6bc72c0c-0e82-4a2c-9834-d57a31a102e5" />

The MeshPages Web Client getting a result from the example `/home` endpoint from the `examples/simple_responses` server.

<img style="width: 30%; height: auto;" alt="MeshPages_Client_Screenshot" src="https://github.com/user-attachments/assets/9ae3c4f4-0057-4e52-84d6-50dbff507857" />
<img style="width: 30%; height: auto;" alt="MeshPages_Client_Screenshot" src="https://github.com/user-attachments/assets/3685bd5c-cfd5-4419-99b2-a9ca28c88d84" />

The Meshtastic Android App experiencing a non-existent endpoint, trying to get the MeshPages exclusive `/home` endpoint, and getting the Meshtastic App compatible `/bees` endpoint from the `examples/simple_responses` server.

## Features

- **MeshPages Web Server**: Serve web pages over Meshtastic mesh networks with a simple FastAPI-like interface
- **MeshPages Web Client**: Browse and request pages from Meshtastic mesh nodes
- **Compression**: Automatic Brotli compression for efficient bandwidth usage
- **Multi-packet Support**: Handle large responses by splitting them into chunks
- **Air Traffic Control**: Intelligent backoff mechanisms to prevent channel congestion
- **Easy Configuration**: Simple, Pythonic API for creating mesh applications

## Quick Start

### Prerequisites

- A Meshtastic radio (e.g., Heltec V3, RAK Wireless) connected via:
  - USB serial port
  - Bluetooth (BLE)
  - Network/TCP (hostname or IP address)
- Python 3.14 or later
- Git

### Installation

#### Option 1: Development Installation (Recommended for Development)

1. Clone this repository:

```bash
git clone https://github.com/MushroomGecko/MeshPages.git
cd MeshPages
```

2. Create a virtual environment:

```bash
python3 -m venv .venv
```

3. Activate the virtual environment:

```bash
source .venv/bin/activate
```

4. Install dependencies and MeshPages in editable mode:

```bash
pip install -e .
pip install -r requirements.txt
```

This allows you to import `meshpages` directly while developing and see changes immediately.

#### Option 2: Production Installation (Standard Package Install)

1. Clone this repository:

```bash
git clone https://github.com/MushroomGecko/MeshPages.git
cd MeshPages
```

2. Create a virtual environment:

```bash
python3 -m venv .venv
```

3. Activate the virtual environment:

```bash
source .venv/bin/activate
```

4. Install the package:

```bash
pip install .
```

### Finding Your Radios

Before connecting to your Meshtastic radio, you can discover available devices:

```bash
./.venv/bin/python helper_utilities/find_radios.py
```

This will list all connected Meshtastic radios organized by connection type:

```
============================================================
Meshtastic Device Discovery
============================================================

[USB Connections]
  - /dev/ttyUSB0

[Bluetooth Connections]
  - MESH_1111 (AA:BB:CC:DD:EE:FF)
  - MESH_2222 (11:22:33:44:55:66)

[Host Connections (TCP/Network)]
  (Device discovery not yet available - use hostname:port manually)
  (Example: 192.168.1.100:4403)
```

**Note**: On Linux, accessing `/dev/ttyUSB`* typically requires elevated privileges. You may need to use `sudo` to access your radio.

## Architecture & Design

### System Overview

Understanding MeshPages' core components will help you use it effectively:

#### Components

- **MeshPagesServer**: Core server API that handles incoming Meshtastic requests, routes, and responses
- **MeshPagesClient**: Client API for requesting pages from Meshtastic mesh nodes
- **AirTrafficControl**: Backoff algorithm for channel utilization management
- **Packet Encoding/Decoding**: Multi-packet assembly and Brotli compression/decompression for Meshtastic transmission

#### How It Works

**MeshPages Web Server** receives requests from Meshtastic mesh nodes

1. Routes the request to the appropriate handler function using decorators
2. Compresses the response and splits it into chunks if necessary
3. Uses **Air Traffic Control** to manage transmission timing and prevent congestion
4. Transmits chunks over the Meshtastic radio network

**MeshPages Web Client** performs the inverse:

1. Accepts web requests for Meshtastic URIs (format: `mesh://!nodeID/path`)
2. Sends requests to the target node via Meshtastic
3. Receives and assembles multi-packet responses
4. Decompresses content and displays it in the browser

### Technical Specifications

#### Packet Format

Responses are split into chunks with the following structure:

```
[Total Chunks (2 hex chars)][Current Chunk ID (2 hex chars)][HTTP Status Code (3 hex chars)][Compressed Content]
```

Example: `6301C8G<brotli-compressed-data>`

- `63` = 99 total chunks
- `01` = chunk 1
- `C8G` = status code (compressed format)
- Rest = compressed content

## MeshPages Web Client

The web client allows you to request pages from mesh nodes and view them in a web browser.

### Running the Client

#### USB Connection (Recommended)

```bash
sudo ./.venv/bin/python client.py --interface-type usb --interface-path /dev/ttyUSB0
```

#### Bluetooth Connection

```bash
# Using device name
sudo ./.venv/bin/python client.py --interface-type bluetooth --interface-path MESH_1111

# Or using MAC address
sudo ./.venv/bin/python client.py --interface-type bluetooth --interface-path AA:BB:CC:DD:EE:FF
```

#### Host Connection (TCP/Network)

```bash
# Using default port (4403)
sudo ./.venv/bin/python client.py --interface-type host --interface-path 192.168.1.100

# Using custom port
sudo ./.venv/bin/python client.py --interface-type host --interface-path 192.168.1.100:5000
```

#### Auto-detect (USB only)

```bash
sudo ./.venv/bin/python client.py
```

The server will start on `http://127.0.0.1:8000` with hot reload enabled for development.

**Important**: `sudo` may be required on Linux to access the `/dev/ttyUSB`* device. If you encounter permission errors, ensure you're using the full path to the venv Python interpreter.

### Accessing the Web Interface

Once running, open your browser and navigate to `http://127.0.0.1:8000` to:

- Enter a mesh URI (e.g., `mesh://!9e9d7a6c/home`)
- Request pages from remote mesh nodes
- View responses and saved pages

## Creating Your Own MeshPages Server

MeshPages uses a FastAPI-inspired decorator pattern for defining routes. Creating a new server is simple:

```python
from meshpages import MeshPagesServer

# Create a server instance - USB connection (auto-detect)
app = MeshPagesServer(
    timeout=300,
    courtousy_interval=3,
)

# Or specify connection explicitly:
# USB with specific device
# app = MeshPagesServer(
#     connection_type="usb",
#     interface_path="/dev/ttyUSB0",
#     timeout=300,
# )

# Bluetooth connection
# app = MeshPagesServer(
#     connection_type="bluetooth",
#     interface_path="MESH_1111",  # or "AA:BB:CC:DD:EE:FF"
#     timeout=300,
# )

# Host (TCP/Network) connection
# app = MeshPagesServer(
#     connection_type="host",
#     interface_path="192.168.1.100:4403",
#     timeout=300,
# )

# Define routes using decorators
@app.page("/home", intended_return_type="html")
def home_page():
    return "<html><body><h1>Hello Mesh!</h1></body></html>"

@app.page("/status", intended_return_type="text")
def status_page():
    return "All systems operational"

# Start the server
app.run()
```

### Running a Custom Server

```bash
sudo ./.venv/bin/python your_server.py
```

### GET-Style Requests with Query Parameters

MeshPages supports GET-style requests where you can pass parameters through a query string, similar to HTTP GET requests. This follows the same **FastAPI-inspired decorator pattern** used throughout MeshPages, where function parameters automatically map to query string parameters.

#### Query String Syntax

Requests with query parameters use the format:

```
/endpoint?parameter1=value1&parameter2=value2&parameter3=value3
```

Example requests:
```
/llm_text?prompt=What+is+the+weather
/secret_html?password=mypassword
/calculate?x=10&y=20
```

#### Defining Endpoints with Parameters

Define your endpoint function with parameters that correspond to query string keys:

```python
from meshpages import MeshPagesServer

app = MeshPagesServer()

@app.page("/greet", intended_return_type="text")
def greet_user(name: str, greeting: str = "Hello"):
    return f"{greeting}, {name}!"

app.run()
```

With this endpoint, clients can request:
```
/greet?name=Alice
/greet?name=Bob&greeting=Hi
```

#### Parameter Types

MeshPages automatically converts query parameters to the specified type. You can use Python type hints to indicate expected parameter types:

```python
@app.page("/calculate", intended_return_type="text")
def calculate(x: int, y: int, operation: str = "add"):
    if operation == "add":
        return str(x + y)
    elif operation == "multiply":
        return str(x * y)
    return "Unknown operation"

@app.page("/settings", intended_return_type="text")
def settings(enabled: bool, timeout: float):
    return f"Enabled: {enabled}, Timeout: {timeout}s"
```

Supported types include: `str`, `int`, `float`, `bool`

#### Special Parameter Types: MeshTypes

For parameters that need special handling within the mesh network, use `MeshType` subclasses. These are automatically populated from the incoming packet rather than from query parameters.

##### Using ClientID

The `ClientID` type automatically extracts the client's mesh node ID from the packet:

```python
from meshpages import MeshPagesServer
from meshpages.types import ClientID

app = MeshPagesServer()

@app.page("/secret_html", intended_return_type="html")
def secret_page(client_id: ClientID, password: str):
    # client_id is automatically populated from the packet
    allowed_clients = ["!a4c3b8f2", "!7d9e2c51"]
    
    if str(client_id) not in allowed_clients:
        return "Unauthorized: You don't have access to this endpoint."
    
    if password != "correct_password":
        return "Unauthorized: Invalid password."
    
    return "<html><body><h1>Welcome!</h1></body></html>"

app.run()
```

When a client sends a request like:
```
/secret_html?password=correct_password
```

The `ClientID` parameter is automatically extracted from the packet's `fromId` field, while `password` comes from the query string.

#### Handling Missing or Optional Parameters

If a parameter is not provided in the query string, it will be set to `None` by the framework. You must handle validation in your function body:

```python
@app.page("/search", intended_return_type="text")
def search(query: str, filter: str = None):
    if query is None:
        return "Error: query parameter is required"
    
    if filter:
        return f"Searching for '{query}' with filter '{filter}'"
    else:
        return f"Searching for '{query}'"

# Both requests work:
# /search?query=meshpages
# /search?query=meshpages&filter=recent

# But this will trigger the error:
# /search
```

There is no automatic validation for required parameters. Even if you don't provide a default value in your function signature, the framework will still pass `None` if the parameter is missing from the query string:

```python
@app.page("/lookup", intended_return_type="text")
def lookup(user_id: str):
    # user_id can still be None if not provided in the query string
    if user_id is None:
        return "Error: user_id parameter is required"
    return f"Looking up user: {user_id}"

# All of these requests will be processed (user_id will be None in the last one):
# /lookup?user_id=12345
# /lookup
```

#### URL Encoding

Query parameters are automatically URL-decoded by `parse_qsl`. Common encodings handled include:

- Spaces: `+`, `%20`, or literal spaces all become space
- Special characters: `%XX` → character (where XX is hex)

```python
@app.page("/message", intended_return_type="text")
def message(text: str):
    return f"Message: {text}"

# All of these work and produce the same result:
# /message?text=hello+world
# /message?text=hello%20world
# /message?text=hello world
```

#### Route Documentation

When a client requests an invalid endpoint, MeshPages automatically generates helpful documentation showing all available routes with their parameter types:

```
Available text routes:
/greet?name=[str]&greeting=[str]
/calculate?x=[int]&y=[int]&operation=[str]
/message?text=[str]

Available html routes:
/secret_html?password=[str]
```

Note: MeshType parameters (like `ClientID`) are not shown in the documentation since they're automatically populated and not user-provided.

#### Examples

See these complete examples for GET-style requests in action:

- **LLM Responses**: `examples/llm_responses/server.py` - Uses query parameters for prompts
- **Secret Responses**: `examples/secret_responses/server.py` - Uses `ClientID` type and password parameter

### Example: Test MeshPages Server

A complete example server is included at `examples/simple_responses/server.py`:

```bash
sudo ./.venv/bin/python examples/simple_responses/server.py
```

This example demonstrates:

- HTML responses with template loading
- Text responses
- Route registration
- Server configuration

## Server Configuration

### Connection Parameters

#### `connection_type` (str, default: "usb")

Type of connection to the Meshtastic device:

- `"usb"` - Serial connection via USB
- `"bluetooth"` - Bluetooth Low Energy (BLE) connection
- `"host"` - Network connection via TCP/IP

#### `interface_path` (str, optional)

Path or address for connecting to the device. Format depends on connection type:

- **USB**: Device path (e.g., `/dev/ttyUSB0`)
- **Bluetooth**: Device name (e.g., `MESH_1111`) or MAC address (e.g., `AA:BB:CC:DD:EE:FF`)
- **Host**: Hostname/IP with optional port (e.g., `192.168.1.100` or `192.168.1.100:4403`)

For USB connections, `None` will auto-detect the first available device.

### Basic Options

#### `timeout` (int, default: 300)

Maximum time in seconds to wait for a response from a remote node before timing out.

#### `courtousy_interval` (float, default: 3.0)

Delay in seconds between sending consecutive response chunks. This gives receiving Meshtastic apps time to process incoming data. Increase this value if you experience packet loss on slower devices.

#### `loop_interval` (float, default: 1.0)

How often (in seconds) the server wakes up to process the request queue.

#### `message_ack` (bool, default: True)

Message acknowledgment style:

- `True`: TCP-style with acknowledgments (reliable, slower)
- `False`: UDP-style without acknowledgments (faster, less reliable)

### Air Traffic Control

Air Traffic Control is an intelligent backoff mechanism that prevents channel congestion by:

1. Tracking radio transmission airtime
2. Calculating current channel utilization
3. Applying delays when utilization exceeds target
4. Allowing bursts when channel is underutilized

This ensures mesh health even during heavy traffic periods.

#### Air Traffic Control Options

##### `air_traffic_control_config` (Config or ChannelPresets, default: ChannelPresets.LONG_FAST)

Meshtastic LoRa radio configuration for data rate calculations. Pre-configured presets available:

- `SHORT_TURBO`, `SHORT_FAST`, `SHORT_SLOW` - Optimized for short range
- `MEDIUM_FAST`, `MEDIUM_SLOW` - Optimized for medium range
- `LONG_TURBO`, `LONG_FAST`, `LONG_MODERATE`, `LONG_SLOW` - Optimized for long range

Or specify a custom `Config` with:

- `sf` (int): Spreading factor (7-12)
- `coding_rate` (float): Error correction rate (4/5, 4/6, 4/7, 4/8)
- `bandwidth_khz` (int): Channel bandwidth (125, 250, or 500 kHz)

##### `air_traffic_control_target_utilization_percent` (float, default: 50.0)

Target channel utilization as a percentage (0-100). The system will apply backoff delays to keep channel usage below this threshold.

##### `air_traffic_control_window_seconds` (float, default: 10.0)

Time window (in seconds) for measuring recent channel activity. Smaller windows respond faster to congestion; larger windows smooth out bursty traffic.

##### `air_traffic_control_meshtastic_overhead_bytes` (int, default: 20)

Protocol overhead added per packet (in bytes). Used for accurate airtime calculations. Rarely needs adjustment.

### Example: Custom Server Configuration

```python
from meshpages import MeshPagesServer, Config
from meshpages.channel_presets import ChannelPresets

app = MeshPagesServer(
    connection_type="usb",
    interface_path="/dev/ttyUSB0",
    timeout=300,                                        # Wait up to 5 minutes for responses
    courtousy_interval=3.0,                             # Measured chunk transmission interval
    loop_interval=0.5,                                # Check queue frequently
    message_ack=True,                                 # Reliable delivery
    air_traffic_control_config=ChannelPresets.LONG_MODERATE,  # Long range, moderate speed
    air_traffic_control_target_utilization_percent=40.0,     # Conservative 40% target
    air_traffic_control_window_seconds=15.0,          # Smooth bursty traffic
)
```

## CLI Tools

### find_radios.py

Discover all connected Meshtastic radios on your system, organized by connection type:

```bash
./.venv/bin/python helper_utilities/find_radios.py
```

Output:

```
============================================================
Meshtastic Device Discovery
============================================================

[USB Connections]
  - /dev/ttyUSB0

[Bluetooth Connections]
  - MESH_1111 (AA:BB:CC:DD:EE:FF)

[Host Connections (TCP/Network)]
  (Device discovery not yet available - use hostname:port manually)
  (Example: 192.168.1.100:4403)
```

Use USB paths for the `--interface-path` parameter with `--interface-type usb`, device names for `--interface-type bluetooth`, and hostname:port for `--interface-type host`.

### list_node_db.py

List all nodes currently stored in the Meshtastic mesh network database:

```bash
# USB connection (auto-detect)
sudo ./.venv/bin/python helper_utilities/list_node_db.py

# Specify connection type and path
sudo ./.venv/bin/python helper_utilities/list_node_db.py --interface-type usb --interface-path /dev/ttyUSB0

# Bluetooth connection
sudo ./.venv/bin/python helper_utilities/list_node_db.py --interface-type bluetooth --interface-path MESH_1111

# Host connection
sudo ./.venv/bin/python helper_utilities/list_node_db.py --interface-type host --interface-path 192.168.1.100:4403
```

Output:

```
Nodes in the node database:
- !1234abcd: Alice Device (ALI) <-- You
- !5678efgh: Bob Device (BOB)
- !9abcdefg: Charlie Device (CHR)
```

This utility helps you identify all node IDs in your mesh network, including your own node, making it easy to connect to and interface with MeshPages servers.

## Troubleshooting

### Permission Denied on /dev/ttyUSB*

**Problem**: `PermissionError` when accessing Meshtastic radio

**Solution**: Use `sudo` with the full path to the venv Python:

```bash
sudo ./.venv/bin/python client.py --interface-type usb --interface-path /dev/ttyUSB1
```

### Multiple Serial Ports or Devices Detected

**Problem**: "Multiple serial ports were detected so one serial port must be specified"

**Solution**: Specify the Meshtastic device explicitly using `--interface-type` and `--interface-path`:

```bash
# USB device
sudo ./.venv/bin/python client.py --interface-type usb --interface-path /dev/ttyUSB1

# Bluetooth device
sudo ./.venv/bin/python client.py --interface-type bluetooth --interface-path MESH_1111

# Host connection
sudo ./.venv/bin/python client.py --interface-type host --interface-path 192.168.1.100:4403
```

### Timeout Errors

**Problem**: Meshtastic nodes not responding within timeout window

**Solutions**:

- Increase `timeout` parameter (default: 300 seconds)
- Reduce `courtousy_interval` to speed up transmission
- Check mesh connectivity with Meshtastic firmware apps
- Verify target node is powered and in range

### High Channel Utilization

**Problem**: Frequent backoff delays or slow responses

**Solutions**:

- Reduce `courtousy_interval` for faster chunk transmission
- Lower `air_traffic_control_target_utilization_percent` to be more conservative

## Development

### Enabling Debug Logging

MeshPages includes comprehensive logging at multiple levels. By default, only INFO level and above are displayed. To see detailed DEBUG logs for troubleshooting:

#### Using Environment Variables (Recommended)

Set the `PYTHONLOGLEVEL` environment variable before running. Place it after `sudo` so it gets passed to the Python process:

**Client with Debug Logging:**

```bash
sudo PYTHONLOGLEVEL=DEBUG ./.venv/bin/python client.py --usb-interface /dev/ttyUSB1
```

**Server with Debug Logging:**

```bash
sudo PYTHONLOGLEVEL=DEBUG ./.venv/bin/python examples/simple_responses/server.py --usb-interface /dev/ttyUSB0
```

**Try other log levels:**

```bash
# View only warnings and errors
sudo PYTHONLOGLEVEL=WARNING ./.venv/bin/python client.py --interface-type usb --interface-path /dev/ttyUSB1

# View all messages including debug
sudo PYTHONLOGLEVEL=DEBUG ./.venv/bin/python client.py --interface-type usb --interface-path /dev/ttyUSB1
```

### Log Levels Explained

MeshPages uses four log levels to organize information:


| Level       | When Displayed                   | What You'll See                                                                        |
| ----------- | -------------------------------- | -------------------------------------------------------------------------------------- |
| **DEBUG**   | Only with `PYTHONLOGLEVEL=DEBUG` | Chunk assembly details, packet decoding, protocol-level operations, route registration |
| **INFO**    | Default                          | Connections, major events, successful operations, important state changes              |
| **WARNING** | Default                          | Timeouts, client unreachable, request mismatches                                       |
| **ERROR**   | Default                          | Failures, exceptions, protocol violations                                              |


### Example Debug Output

```
2026-04-18 14:32:45,123 - meshpages.meshpages_server - DEBUG - Server initialized with loop_interval=1.0s, timeout=300s, courtesy_interval=3.0s
2026-04-18 14:32:45,124 - meshpages.meshpages_server - DEBUG - Registering route: /home (returns html)
2026-04-18 14:32:46,456 - meshpages.meshpages_server - DEBUG - Received request from !abc123: type=html, route=<recognized>
2026-04-18 14:32:46,457 - meshpages.meshpages_server - DEBUG - Successfully decoded HTML request from !abc123
2026-04-18 14:32:46,458 - meshpages.meshpages_server - DEBUG - Sending HTML response chunk 1/1 to !abc123
2026-04-18 14:32:46,459 - meshpages.meshpages_server - DEBUG - Transmitted HTML chunk 1/1
2026-04-18 14:32:46,460 - meshpages.meshpages_server - INFO - Channel congestion: applied 0.50s backoff delay before sending HTML chunk to !abc123
```

### Debugging Common Issues

**Issue**: "Received request from !abc123: type=html, route=<not found>"

- DEBUG log shows the route wasn't recognized
- Check that the endpoint path registered matches the request path exactly

**Issue**: "Empty decompressed payload from !abc123, treating as text fallback"

- DEBUG log shows decompression returned empty data
- Could indicate corrupted transmission or incompatible compression

**Issue**: Frequent backoff delays appearing in logs

- Check channel utilization with `air_traffic_control_target_utilization_percent`
- Monitor the `Applied backoff delay` INFO messages to see congestion patterns

### Code Style

This project follows PEP 8 conventions with type hints throughout.

## Contributing

Contributions are welcome! Please submit pull requests or open issues for bugs and feature requests.

## Support

For issues with Meshtastic hardware, see: [https://meshtastic.org/](https://meshtastic.org/)
For questions about MeshPages, open an issue in this repository.
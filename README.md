# MeshPages

MeshPages enables web-based communication over Meshtastic mesh networks. It allows you to request and serve web pages directly over Meshtastic radios, turning your Meshtastic device into a wireless web server and client.

## Features

- **MeshPages Web Server**: Serve web pages over Meshtastic mesh networks with a simple FastAPI-like interface
- **MeshPages Web Client**: Browse and request pages from Meshtastic mesh nodes
- **Compression**: Automatic Brotli compression for efficient bandwidth usage
- **Multi-packet Support**: Handle large responses by splitting them into chunks
- **Air Traffic Control**: Intelligent backoff mechanisms to prevent channel congestion
- **Easy Configuration**: Simple, Pythonic API for creating mesh applications

## Quick Start

### Prerequisites

- A Meshtastic radio (e.g., Heltec V3, RAK Wireless) connected via USB
- Python 3.14 or later
- Git

### Installation

1. Clone this repository:

```bash
git clone https://github.com/MushroomGecko/MeshPages.git
cd MeshPages
```

1. Create a virtual environment:

```bash
python3 -m venv .venv
```

1. Activate the virtual environment:

```bash
source .venv/bin/activate
```

1. Install dependencies:

```bash
pip install -r requirements.txt
```

### Finding Your Radios

Before connecting to your Meshtastic radio, you can discover available USB devices:

```bash
./.venv/bin/python find_radios.py
```

This will list all connected Meshtastic radios and their device paths (e.g., `/dev/ttyUSB0`).

**Note**: On Linux, accessing `/dev/ttyUSB`* typically requires elevated privileges. You may need to use `sudo` to access your radio.

## Architecture & Design

### System Overview

Understanding MeshPages' core components will help you use it effectively:

#### Components

- **MeshPageServer**: Core server API that handles incoming Meshtastic requests, routes, and responses
- **MeshPageClient**: Client API for requesting pages from Meshtastic mesh nodes
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

#### With USB Device Specification (Recommended)

```bash
sudo ./.venv/bin/python client.py --usb-interface /dev/ttyUSB1
```

#### Without CLI Arguments (Auto-detect)

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
from meshpages import MeshPageServer

# Create a server instance
app = MeshPageServer(
    usb_interface="/dev/ttyUSB0",  # or None to auto-detect
    timeout=60,
    courtousy_interval=2.5,
)

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

### Basic Options

#### `usb_interface` (str, optional)

USB device path for the Meshtastic radio (e.g., `/dev/ttyUSB0`). If `None`, auto-detects the first available radio.

#### `timeout` (int, default: 60)

Maximum time in seconds to wait for a response from a remote node before timing out.

#### `courtousy_interval` (float, default: 2.5)

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
from meshpages import MeshPageServer, Config
from meshpages.channel_presets import ChannelPresets

app = MeshPageServer(
    usb_interface="/dev/ttyUSB0",
    timeout=120,                                        # Wait up to 2 minutes for responses
    courtousy_interval=1.0,                           # Fast chunk transmission
    loop_interval=0.5,                                # Check queue frequently
    message_ack=True,                                 # Reliable delivery
    air_traffic_control_config=ChannelPresets.LONG_MODERATE,  # Long range, moderate speed
    air_traffic_control_target_utilization_percent=40.0,     # Conservative 40% target
    air_traffic_control_window_seconds=15.0,          # Smooth bursty traffic
)
```

## CLI Tools

### find_radios.py

Discover all connected Meshtastic radios on your system:

```bash
./.venv/bin/python find_radios.py
```

Output:

```
Found Meshtastic devices on:
- /dev/ttyUSB0
- /dev/ttyUSB1
```

Use this to identify device paths for the `--usb-interface` parameter.

## Troubleshooting

### Permission Denied on /dev/ttyUSB*

**Problem**: `PermissionError` when accessing Meshtastic radio

**Solution**: Use `sudo` with the full path to the venv Python:

```bash
sudo ./.venv/bin/python client.py --usb-interface /dev/ttyUSB1
```

### Multiple Serial Ports Detected

**Problem**: "Multiple serial ports were detected so one serial port must be specified"

**Solution**: Specify the Meshtastic device explicitly:

```bash
sudo ./.venv/bin/python client.py --usb-interface /dev/ttyUSB1
# or
sudo ./.venv/bin/python examples/simple_responses/server.py --usb-interface /dev/ttyUSB0
```

### Timeout Errors

**Problem**: Meshtastic nodes not responding within timeout window

**Solutions**:

- Increase `timeout` parameter (default: 60 seconds)
- Reduce `courtousy_interval` to speed up transmission
- Check mesh connectivity with Meshtastic firmware apps
- Verify target node is powered and in range

### High Channel Utilization

**Problem**: Frequent backoff delays or slow responses

**Solutions**:

- Reduce `courtousy_interval` for faster chunk transmission
- Lower `air_traffic_control_target_utilization_percent` to be more conservative

## Development

### Code Style

This project follows PEP 8 conventions with type hints throughout.

## Contributing

Contributions are welcome! Please submit pull requests or open issues for bugs and feature requests.

## Support

For issues with Meshtastic hardware, see: [https://meshtastic.org/](https://meshtastic.org/)
For questions about MeshPages, open an issue in this repository.
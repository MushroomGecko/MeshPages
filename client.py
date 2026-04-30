import argparse
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from meshpages import MeshPagesClient
from meshpages.utils import parse_file_path, parse_uri

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Parse CLI arguments at module load time (before FastAPI app initialization)
parser = argparse.ArgumentParser(description="MeshPages client: request web pages from mesh network nodes")
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
    help="Path for the connection: device path for USB (e.g., /dev/ttyUSB0), device name or MAC for Bluetooth (e.g., MESH_1111 or AA:BB:CC:DD:EE:FF), or 'hostname:port' for host connections (e.g., 192.168.1.100:4403).",
)
args = parser.parse_args()

templates = Jinja2Templates(directory="templates")

# Global meshpage client instance, initialized during app startup
meshpage = None


def save_page(
    node_id: str,
    path: str,
    content: str,
) -> str:
    """
    Save retrieved page content to the local filesystem.

    Organizes saved pages in a directory structure by node_id to avoid collisions.

    Parameters:
        node_id (str): The mesh node ID (! prefix is stripped if present).
        path (str): The page path on the remote node.
        content (str): The HTML content to save.

    Returns:
        str: The full filesystem path where the page was saved.
    """

    # Resolve the path to a full filesystem path
    full_path = parse_file_path(node_id, path, base_path="saved_pages")

    # Create parent directories if they don't exist
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    # Write the content to the file
    with open(full_path, "w") as file:
        file.write(content)

    return full_path


def get_saved_page(
    node_id: str,
    path: str,
) -> str:
    """
    Retrieve a previously saved page from the local filesystem.

    Attempts to load a page that was previously fetched and stored locally.
    Returns None if the file doesn't exist or if an error occurs during reading.

    Parameters:
        node_id (str): The mesh node ID (! prefix is stripped if present).
        path (str): The page path on the remote node.

    Returns:
        str: The HTML content of the saved page, or None if not found or on error.
    """
    # Resolve the path to a full filesystem path using the saved_pages directory
    full_path = parse_file_path(node_id, path, base_path="saved_pages")

    # Attempt to read the file if it exists
    if os.path.exists(full_path):
        try:
            with open(full_path, "r") as file:
                return file.read()
        except Exception as e:
            # Log error and return None to indicate retrieval failed
            logger.error(f"Error reading file {full_path}: {e}")
            return None
    # File doesn't exist in saved_pages
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage app lifecycle: connect to mesh on startup, disconnect on shutdown.

    Initializes the MeshPagesClient and establishes the radio connection when the
    app starts, then cleanly closes the connection when the app shuts down.

    Parameters:
        app (FastAPI): The FastAPI application instance.

    Returns:
        None
    """
    global meshpage

    connection_type = args.interface_type
    interface_path = args.interface_path

    # Log connection attempt with appropriate message
    if interface_path:
        logger.info(f"Connecting to radio on {connection_type} interface: {interface_path}...")
    else:
        logger.info(f"Connecting to radio with default {connection_type} interface...")

    # Initialize the mesh client and establish radio connection
    meshpage = MeshPagesClient(
        connection_type=connection_type,
        interface_path=interface_path,
        timeout=300,
    )

    # Yield control back to FastAPI; the server runs until shutdown
    yield

    # Clean up: close the radio connection on app shutdown
    logger.info("Disconnecting from radio...")


app = FastAPI(lifespan=lifespan)


@app.post("/search")
def search(
    request: Request,
    query: str = Form(...),
    action: str = Form("search"),
) -> dict:
    """
    Handle page search requests via mesh network.

    Parses the query URI, requests the page from the remote node, and saves
    the response to local storage before rendering results.

    Parameters:
        request (Request): The HTTP request object provided by FastAPI.
        query (str): The mesh URI query string submitted via HTML form.

    Returns:
        dict: A TemplateResponse containing the rendered results.html template.
    """
    # Parse the query string into node_id and path components
    node_id, path = parse_uri(query)

    # Attempt to retrieve the page from the mesh network
    if node_id and path:
        # If user clicked "Quick Search", prioritize cached pages
        if action == "quick-search":
            content = get_saved_page(node_id, path)
            if content:
                logger.info(f"Using cached page for {query}")
                # Return early with cached content, skip mesh request
                return templates.TemplateResponse(
                    request=request,
                    name="results.html",
                    context={"query": query, "content": content},
                )
        # Request fresh page from mesh network (or if quick-search had no cached result)
        response = meshpage.request_page(node_id, path)
        if response:
            logger.info(f"Retrieved page from mesh for {query} and saved to cache")
            content = response
            # Persist the retrieved content to local storage for future quick-searches
            save_page(node_id, path, content)
        else:
            # Remote node did not return content or timed out
            content = "<p>Node not found</p>"
    else:
        # Query format was invalid or unparseable
        content = "<p>Invalid query</p>"

    # Render the results template with the query and content
    return templates.TemplateResponse(
        request=request,
        name="results.html",
        context={"query": query, "content": content},
    )


@app.get("/")
def index(request: Request):
    """
    Serve the home page.

    Renders the index.html template when accessing the root path.

    Parameters:
        request (Request): The HTTP request object provided by FastAPI.

    Returns:
        TemplateResponse: The rendered index.html template.
    """
    return templates.TemplateResponse(
        request=request,
        name="index.html",
    )


# Mount static file directories for CSS, JavaScript, and other assets
app.mount("/static", StaticFiles(directory="static"), name="static")


def main():
    """
    Start the FastAPI server with hot reload.

    The CLI arguments are parsed at module load time (before this function runs),
    so they're available to the lifespan hook regardless of uvicorn's reload behavior.

    Parameters:
        None

    Returns:
        None
    """
    logger.info("Starting server on http://127.0.0.1:8000")
    uvicorn.run("client:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()

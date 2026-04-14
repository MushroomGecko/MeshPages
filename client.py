import argparse
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from meshpages import MeshPageClient
from meshpages.utils import parse_uri

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Parse CLI arguments at module load time (before FastAPI app initialization)
parser = argparse.ArgumentParser(description="MeshPages client: request web pages from mesh network nodes")
parser.add_argument(
    "--usb-interface",
    type=str,
    default=None,
    help="USB interface for the radio connection (e.g., /dev/ttyUSB0). If not specified, uses default.",
)
args = parser.parse_args()

templates = Jinja2Templates(directory="templates")

# Global meshpage client instance, initialized during app startup
meshpage = None


# TODO: Fully implement this function
def save_page(node_id: str, path: str, content: str) -> str:
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
    # Remove the "!" prefix from node_id if present (mesh protocol convention)
    if node_id.startswith("!"):
        node_id = node_id[1:]

    # Construct the filesystem path: saved_pages/<node_id>/<path>.html
    full_path = os.path.join("saved_pages", node_id, f"{path}.html")

    # Create parent directories if they don't exist
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    # Write the content to the file
    with open(full_path, "w") as file:
        file.write(content)

    return full_path


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage app lifecycle: connect to mesh on startup, disconnect on shutdown.

    Initializes the MeshPageClient and establishes the radio connection when the
    app starts, then cleanly closes the connection when the app shuts down.

    Parameters:
        app (FastAPI): The FastAPI application instance.

    Returns:
        None
    """
    global meshpage

    # Use usb_interface from module-level args (parsed at module load time)
    usb_interface = args.usb_interface

    # Log connection attempt with appropriate message
    if usb_interface:
        logger.info(f"Connecting to radio on {usb_interface}...")
    else:
        logger.info("Connecting to radio with default interface...")

    # Initialize the mesh client and establish radio connection
    meshpage = MeshPageClient(usb_interface=usb_interface)

    # Yield control back to FastAPI; the server runs until shutdown
    yield

    # Clean up: close the radio connection on app shutdown
    logger.info("Disconnecting from radio...")


app = FastAPI(lifespan=lifespan)


@app.post("/search")
def search(request: Request, query: str = Form(...)) -> dict:
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
        trace = meshpage.request_page(node_id, path)
        if trace:
            content = trace
            # TODO: Fully implement this function
            # Persist the retrieved content to local storage
            # save_page(node_id, path, content)
        else:
            # Remote node did not return content
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


# Mount static file directories for CSS, JavaScript, and other assets
app.mount("/static", StaticFiles(directory="static"), name="static")
# Mount templates directory at root path
app.mount("/", StaticFiles(directory="templates"), name="templates")


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

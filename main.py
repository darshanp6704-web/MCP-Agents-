import os
import sys

# Resolve path to the google-mcp-server subdirectory and add it to sys.path
base_dir = os.path.dirname(os.path.abspath(__file__))
mcp_server_dir = os.path.join(base_dir, 'google-mcp-server')
if mcp_server_dir not in sys.path:
    sys.path.insert(0, mcp_server_dir)

# Import the FastAPI app from the server module
from server import app

if __name__ == "__main__":
    import uvicorn
    # Support local running from the root directory
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    uvicorn.run(app, host=host, port=port)

import os
import sys

# Statically import the FastAPI app from the google_mcp_server package.
# This prevents IDE linting/type errors and works out of the box.
from google_mcp_server.server import app

if __name__ == "__main__":
    import uvicorn
    # Support local running from the root directory
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    uvicorn.run(app, host=host, port=port)



import os
import sys

# Ensure this directory is in the sys.path so server can import relative modules
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from server import app
except ImportError:
    from .server import app


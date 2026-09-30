"""Stable source entry-point location used by packaged and development tools."""
from pathlib import Path

SERVER_FILE = str(Path(__file__).resolve().parents[1] / "server.py")

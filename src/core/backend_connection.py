"""Canonical local-backend connection settings shared by API, CLI and MCP.

This is a local IPC boundary, not a remote deployment configuration. Supporting
remote hosts requires a separate authenticated transport design.
"""

import ipaddress
import os
from urllib.parse import urlsplit

DEFAULT_BACKEND_BASE_URL = "http://127.0.0.1:8000"


def normalize_backend_url(value: str) -> str:
    if not isinstance(value, str) or "\\" in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Vantage backend URL must be a valid loopback URL.")
    selected = value.strip().rstrip("/")
    try:
        parsed = urlsplit(selected)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("Vantage backend URL must be a valid loopback URL.") from None
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Vantage backend URL must use HTTP or HTTPS.")
    if not host or parsed.username or parsed.password or parsed.query or parsed.fragment or port == 0:
        raise ValueError("Vantage backend URL must be a valid loopback URL.")
    try:
        loopback = host.lower() == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise ValueError("Vantage backend URL must use a loopback host.")
    return selected


def resolve_backend_url(value=None, *, env=None):
    env = os.environ if env is None else env
    configured = value or env.get("VANTAGE_BACKEND_URL")
    if not configured:
        host = env.get("VANTAGE_BACKEND_HOST") or "127.0.0.1"
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = env.get("VANTAGE_BACKEND_PORT") or "8000"
        configured = f"http://{host}:{port}"
    return normalize_backend_url(configured)


def backend_bind_address(*, env=None):
    """Resolve a directly hostable HTTP endpoint; fail closed on proxy URLs."""
    parsed = urlsplit(resolve_backend_url(env=env))
    if parsed.scheme != "http" or parsed.path not in {"", "/"}:
        raise ValueError("An HTTPS or path-prefixed backend URL must use an already running backend.")
    return parsed.hostname, parsed.port or 80

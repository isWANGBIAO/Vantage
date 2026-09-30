"""Loopback-only automation boundary and explicit local-action intent checks."""

import ipaddress
import os
import re

from fastapi import Request
from fastapi.responses import JSONResponse

DEFAULT_BACKEND_BIND_HOST = "127.0.0.1"

def _get_backend_bind_host(env=None):
    source = env if env is not None else os.environ
    host = (source.get("VANTAGE_BACKEND_HOST") or "").strip()
    return host or DEFAULT_BACKEND_BIND_HOST

def _normalize_host_value(value):
    if value is None:
        return ""
    host = str(value).strip().lower()
    if not host:
        return ""

    if host.startswith("["):
        closing_bracket = host.find("]")
        if closing_bracket < 0:
            return ""
        address_text = host[1:closing_bracket]
        port_suffix = host[closing_bracket + 1:]
        if port_suffix and (
            not port_suffix.startswith(":")
            or not re.fullmatch(r"[0-9]{1,5}", port_suffix[1:])
            or int(port_suffix[1:]) > 65535
        ):
            return ""
        try:
            address = ipaddress.ip_address(address_text)
        except ValueError:
            return ""
        return str(address) if isinstance(address, ipaddress.IPv6Address) else ""

    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        if ":" not in host:
            return host
        if host.count(":") != 1:
            return ""
        hostname, port = host.rsplit(":", 1)
        if not hostname or not re.fullmatch(r"[0-9]{1,5}", port) or int(port) > 65535:
            return ""
        return hostname

def _is_loopback_host(value):
    host = _normalize_host_value(value)
    if host in {"localhost", "testclient", "testserver"}:
        return True
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback

def _has_local_action_intent(headers, expected_intent):
    try:
        actual = headers.get("x-vantage-intent")
    except AttributeError:
        actual = None
    return actual == expected_intent

TRUSTED_BROWSER_ORIGINS = frozenset({
    "http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000",
})


async def enforce_loopback_backend_access(request: Request, call_next):
    protected = request.url.path.startswith(("/api/automation/", "/api/v1/"))
    protected = protected or request.url.path == "/api/action_plan"
    if not protected:
        return await call_next(request)

    client_host = getattr(request.client, "host", "")
    host_header = request.headers.get("host", "")
    if not _is_loopback_host(client_host) or not _is_loopback_host(host_header):
        return JSONResponse(status_code=403, content={"error": "Local backend access only"})
    # CORS only controls reading responses; simple cross-site POSTs still reach
    # handlers. Native clients omit Origin, and the trusted app-scheme proxy
    # deliberately does not forward browser-controlled origin headers.
    origin = request.headers.get("origin")
    if origin is not None and origin not in TRUSTED_BROWSER_ORIGINS:
        return JSONResponse(status_code=403, content={"error": "Untrusted browser origin"})
    return await call_next(request)

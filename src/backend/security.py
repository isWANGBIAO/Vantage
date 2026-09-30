"""Local-only HTTP/WebSocket boundary and explicit local-action intent checks."""

import ipaddress
import os
import re

from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

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
    if host == "localhost":
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
    "http://localhost:5173", "http://127.0.0.1:5173",
})


def _backend_access_error(scope: Scope) -> str | None:
    headers = Headers(scope=scope)
    client = scope.get("client")
    client_host = client[0] if client else ""
    # Reject ambiguous routing/source headers rather than depending on which
    # duplicate value a proxy, ASGI server, or application happens to select.
    hosts = headers.getlist("host")
    if len(hosts) != 1 or not _is_loopback_host(client_host) or not _is_loopback_host(hosts[0]):
        return "Local backend access only"
    # CORS only controls reading responses; simple cross-site POSTs still reach
    # handlers. Native clients omit Origin, and the trusted app-scheme proxy
    # deliberately does not forward browser-controlled origin headers.
    origins = headers.getlist("origin")
    if len(origins) > 1 or (origins and origins[0] not in TRUSTED_BROWSER_ORIGINS):
        return "Untrusted browser origin"
    # Browser image/navigation requests can omit Origin. Fetch Metadata still
    # identifies cross-site requests; native clients and the app proxy omit it.
    if not origins and headers.get("sec-fetch-site", "").lower() == "cross-site":
        return "Untrusted browser origin"
    return None


class LoopbackAccessMiddleware:
    """Protect every route, mounted private file, and WebSocket before dispatch.

    This is intentionally path-independent: new API versions and mounted media
    must not accidentally fall outside the application's local IPC boundary.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] in {"http", "websocket"}:
            error = _backend_access_error(scope)
            if error is not None:
                if scope["type"] == "websocket":
                    # Closing before accept denies the handshake (HTTP 403).
                    await send({"type": "websocket.close", "code": 1008, "reason": error})
                else:
                    await JSONResponse(status_code=403, content={"error": error})(scope, receive, send)
                return
        await self.app(scope, receive, send)

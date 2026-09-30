"""Bounded, redirect-free loopback transport and reconnectable job observation.

This module uses only Python's standard library and never reads backend config
files. Credentials only travel in request bodies, never in URLs or diagnostics.
"""
from __future__ import annotations

import copy
import ipaddress
import json
import os
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

MAX_LINE = 1024 * 1024
MAX_RESPONSE = 32 * 1024 * 1024
TERMINAL = {"succeeded", "failed", "cancelled"}


class ClientError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def backend_url(value=None, env=None):
    env = os.environ if env is None else env
    value = value or env.get("VANTAGE_BACKEND_URL")
    if not value:
        host = env.get("VANTAGE_BACKEND_HOST", "127.0.0.1")
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        value = f"http://{host}:{env.get('VANTAGE_BACKEND_PORT', '8000')}"
    if not isinstance(value, str) or "\\" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ClientError("Backend address must be a loopback HTTP(S) URL")
    value = value.strip().rstrip("/")
    try:
        parsed = urllib.parse.urlsplit(value)
        host = parsed.hostname
        port = parsed.port
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        loopback = False
    if not loopback or parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or parsed.query or parsed.fragment or port == 0:
        raise ClientError("Backend address must be a loopback HTTP(S) URL without credentials or query")
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, base_url=None, timeout=30):
        self.base_url = backend_url(base_url)
        self.timeout = timeout
        self.active = {}
        self.active_lock = threading.Lock()
        # Local IPC must not be passed through ambient HTTP proxies.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def open(self, path, method="GET", body=None, headers=None, timeout=None):
        if not path.startswith(("/api/v1/", "/static/photos/", "/static/screenshots/", "/static/plots/")) or "\\" in path or "://" in path or any(p in {".", ".."} for p in urllib.parse.unquote(path).split("/")):
            raise ClientError("Unsupported backend resource")
        request_headers = {"Accept": "application/json", **(headers or {})}
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=body, method=method, headers=request_headers)
        try:
            return self.opener.open(request, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            raise ClientError(f"Backend returned HTTP {status}", status) from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise ClientError("Cannot reach the local backend; retry after it is ready") from None

    def request(self, path, method="GET", body=None, headers=None):
        with self.open(path, method, body, headers) as response:
            data = response.read(MAX_RESPONSE + 1)
        if len(data) > MAX_RESPONSE:
            raise ClientError("Backend response exceeds the safe size limit")
        try:
            return json.loads(data)
        except (ValueError, UnicodeError):
            raise ClientError("Backend returned invalid JSON") from None

    def cancel_stream(self, path):
        with self.active_lock:
            responses = list(self.active.get(path, ()))
        for response in responses:
            try:
                response.fp.raw._sock.shutdown(socket.SHUT_RDWR)
            except (AttributeError, OSError):
                pass
            try:
                response.close()
            except OSError:
                pass

    def stream(self, path, method="GET", body=None, stop=None):
        response = self.open(path, method, body, {"Accept": "application/x-ndjson"})
        with self.active_lock:
            self.active.setdefault(path, set()).add(response)
        try:
            while not (stop and stop.is_set()):
                try:
                    line = response.readline(MAX_LINE + 1)
                except (OSError, ValueError, AttributeError):
                    if stop and stop.is_set():
                        return
                    raise ClientError("Stream connection interrupted") from None
                if not line:
                    return
                if len(line) > MAX_LINE:
                    raise ClientError("Stream record exceeds the safe size limit")
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeError):
                    raise ClientError("Backend returned invalid NDJSON") from None
                if not isinstance(event, dict):
                    raise ClientError("Stream record must be an object")
                yield event
        finally:
            response.close()
            with self.active_lock:
                self.active.get(path, set()).discard(response)

    def download(self, path):
        with self.open(path) as response:
            value = response.read(MAX_RESPONSE + 1)
        if len(value) > MAX_RESPONSE:
            raise ClientError("Download exceeds the safe size limit")
        return value

    def transcribe(self, path):
        path = Path(path)
        if path.stat().st_size > MAX_RESPONSE:
            raise ClientError("Audio exceeds the 32 MiB upload limit")
        boundary = "Vantage" + uuid.uuid4().hex
        # Fixed wire filename avoids injecting user-selected filenames into headers.
        suffix = path.suffix.lower() if path.suffix.lower() in {".wav", ".webm", ".mp3", ".ogg", ".flac", ".m4a"} else ".bin"
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio{suffix}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode())
        return self.request("/api/v1/media/transcribe", "POST", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})

    def frames(self, stop):
        path = "/api/v1/camera/stream"
        response = self.open(path, timeout=10)
        with self.active_lock:
            self.active.setdefault(path, set()).add(response)
        try:
            pending = bytearray()
            while not stop.is_set():
                try:
                    chunk = response.read1(16384)
                except (OSError, ValueError, AttributeError):
                    if stop.is_set():
                        return
                    raise ClientError("Camera stream interrupted") from None
                if not chunk:
                    return
                pending.extend(chunk)
                while True:
                    start = pending.find(b"\xff\xd8")
                    end = pending.find(b"\xff\xd9", start + 2) if start >= 0 else -1
                    if end < 0:
                        break
                    yield bytes(pending[start:end + 2])
                    del pending[:end + 2]
                if len(pending) > MAX_RESPONSE:
                    raise ClientError("Camera frame exceeds the safe size limit")
        finally:
            response.close()
            with self.active_lock:
                self.active.get(path, set()).discard(response)


def provider_patch(state, route, values, key=None, clear_key=False):
    """Preserve the *entire* provider set; omit masked keys, never read secrets."""
    if not route.strip():
        raise ClientError("Provider route is required")
    providers = copy.deepcopy(state.get("provider", {}).get("providers", {}))
    for provider in providers.values():
        provider.pop("api_key", None)
    entry = providers.setdefault(route, {"route": route, "type": "openai-compatible", "enabled": True, "models": []})
    entry.update(values)
    if clear_key:
        entry["api_key"] = ""
    elif key:
        entry["api_key"] = key
    return {"provider_config": {"selected_provider": route, "providers": providers}}


def payload_text(value):
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, str) else str(parsed)
    except (ValueError, TypeError):
        return value


class JobObserver:
    """One observer; stopping observation never cancels backend work.

    Truncation discards partial text. EOF is never success. Reconnect resumes
    from the monotonic cursor; a backend restart returns the current saved plan.
    """
    def __init__(self, client, job_id):
        self.client = client
        self.job_id = job_id
        self.cursor = 0
        self.stop = threading.Event()

    def run(self, emit):
        delay = 0.25
        path = "/api/v1/action-plan/jobs/" + urllib.parse.quote(self.job_id, safe="")
        while not self.stop.is_set():
            try:
                snapshot = self.client.request(path)
                emit("snapshot", snapshot)
                if snapshot.get("status") in TERMINAL:
                    if snapshot["status"] == "succeeded":
                        saved = snapshot.get("result") or {}
                        if snapshot.get("error") or not complete_result(saved):
                            emit("invalid_result", {"message": "The successful job has no complete verified result"})
                            return
                        result = self.client.request("/api/v1/action-plan/today")
                        identity_keys = [k for k in ("id", "filename", "date") if saved.get(k) is not None]
                        if not complete_result(result) or not identity_keys or any(saved[k] != result.get(k) for k in identity_keys):
                            emit("invalid_result", {"message": "The current saved plan does not match this job's result"})
                            return
                        emit("result", result)
                    return
                for event in self.client.stream(f"{path}/events?after={self.cursor}", stop=self.stop):
                    if event.get("truncated") or event.get("event_truncated"):
                        self.cursor = max(self.cursor, int(event.get("cursor") or event.get("sequence") or 0))
                        emit("truncated", event)
                        break
                    sequence = event.get("sequence")
                    if not isinstance(sequence, int) or sequence <= self.cursor:
                        continue
                    self.cursor = sequence
                    emit("event", event)
                    if event.get("done") or event.get("error") or event.get("job_status") in TERMINAL:
                        break
                # Always verify authoritative state after terminal records or EOF.
                delay = 0.25
            except ClientError as exc:
                if exc.status == 404:
                    emit("restarted", {"today": self.client.request("/api/v1/action-plan/today"), "jobs": self.client.request("/api/v1/action-plan/jobs")})
                    return
                emit("reconnecting", {"message": str(exc)})
                delay = min(delay * 2, 10)
            if self.stop.wait(delay):
                return


def complete_result(result):
    return bool(isinstance(result, dict) and result.get("exists") is True and not result.get("error") and all(isinstance(result.get(k), dict) and isinstance(result[k].get("body"), str) and result[k]["body"].strip() for k in ("analysis", "plan")))

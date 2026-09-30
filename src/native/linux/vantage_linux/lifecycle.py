"""Connect once; optionally supervise only the backend this client started."""
from __future__ import annotations
import fcntl
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit
from .client import ClientError


class BackendHost:
    def __init__(self, client, command=None, data_dir=None):
        self.client = client
        self.command = command
        self.process = None
        self.lock = None
        self.data_dir = Path(data_dir or os.environ.get("VANTAGE_DATA_DIR") or Path.home() / ".local/share/Vantage")

    def ready(self):
        self.client.request("/api/v1/system/status")
        capabilities = self.client.request("/api/v1/capabilities")
        if str(capabilities.get("api_version", "")).split(".")[0] != "1":
            raise ClientError("The backend API major version is not supported")
        if capabilities.get("service") != "vantage":
            raise ClientError("This endpoint is not a Vantage backend")
        return capabilities

    def connect(self, timeout=90):
        try:
            return self.ready()
        except ClientError as exc:
            if exc.status or not str(exc).startswith("Cannot reach"):
                raise
        if not self.command:
            raise ClientError("Backend is not running. Start the backend, or launch with --backend-runtime /path/to/VantageBackend or --backend-python /path/to/venv/bin/python")
        endpoint = urlsplit(self.client.base_url)
        if endpoint.scheme != "http" or endpoint.path not in {"", "/"}:
            raise ClientError("HTTPS/path-prefixed backends must already be running")
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = (self.data_dir / "linux-backend.lock").open("a+")
        try:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            self.lock = None
        if self.lock:
            # Close the check/start race with another native instance.
            try:
                return self.ready()
            except ClientError as exc:
                if exc.status or not str(exc).startswith("Cannot reach"):
                    raise
            env = {**os.environ, "VANTAGE_APP_MODE": "packaged", "VANTAGE_DATA_DIR": str(self.data_dir), "VANTAGE_BACKEND_URL": self.client.base_url}
            self.process = subprocess.Popen(self.command, env=env, cwd=self.data_dir, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process and self.process.poll() is not None:
                raise ClientError("The backend exited before it became ready; inspect the backend logs in the data directory")
            try:
                return self.ready()
            except ClientError as exc:
                if exc.status or not str(exc).startswith("Cannot reach"):
                    raise
            time.sleep(0.3)
        raise ClientError("Backend startup timed out. Retry connection or inspect backend logs")

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None
        if self.lock:
            self.lock.close()
            self.lock = None

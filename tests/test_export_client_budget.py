"""Finite client budgets must cover the backend's valid export budget."""
import asyncio
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from mcp import Client

from src.mcp_server import create_mcp_server
from src.services.vantage_client import VantageClient, VantageClientError


def test_default_cli_and_mcp_accept_a_31_second_export(tmp_path):
    payload = b"synthetic-download-not-a-real-xlsx"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(31)
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    target = tmp_path / "export.xlsx"
    target.write_bytes(b"prior export")

    async def exercise():
        async def cli():
            return await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "src.cli", "--base-url", url,
                                                           "face", "export", "--output", str(target)],
                                           capture_output=True, text=True, timeout=45)

        async def mcp():
            async with Client(create_mcp_server(base_url=url)) as client:
                return await client.call_tool("face.export", {})

        return await asyncio.gather(cli(), mcp())

    try:
        cli, mcp = asyncio.run(exercise())
        assert cli.returncode == 0, cli.stderr
        assert target.read_bytes() == payload
        assert not mcp.is_error
        assert mcp.structured_content["size_bytes"] == len(payload)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_timeout_is_distinguished_from_backend_connection_refusal():
    import requests
    from unittest.mock import Mock

    session = Mock()
    session.request.side_effect = requests.exceptions.ReadTimeout("synthetic timeout")
    with pytest.raises(VantageClientError) as error:
        VantageClient(session=session, timeout=0.1).invoke("face.export")
    assert "timed out" in str(error.value).lower()
    assert "unavailable" not in str(error.value).lower()

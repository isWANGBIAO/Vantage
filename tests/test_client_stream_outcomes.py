"""The CLI and MCP must agree on business completion, not just HTTP 200."""
import asyncio
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from mcp import Client

from src.mcp_server import create_mcp_server
from src import cli
from unittest.mock import Mock


@pytest.mark.parametrize("events,success", [
    ([{"error": "synthetic failure"}], False),
    ([{"log": 'STREAM_ERROR:"synthetic failure"'}], False),
    ([{"log": "partial"}], False),
    ([], False),
    ([{"error": "synthetic failure"}, {"done": True}], False),
    ([{"log": "complete"}, {"done": True}], True),
])
def test_cli_and_mcp_require_successful_chat_completion(events, success):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = "".join(json.dumps(event) + "\n" for event in events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        cli = subprocess.run([sys.executable, "-m", "src.cli", "--base-url", url,
                              "--format", "json", "chat", "send", "--message", "synthetic"],
                             capture_output=True, text=True, timeout=15)
        assert (cli.returncode == 0) is success
        emitted = [json.loads(line) for line in cli.stdout.splitlines()]
        assert emitted == (events[:1] if events and "error" in events[0] else events)

        async def call():
            async with Client(create_mcp_server(base_url=url)) as client:
                return await client.call_tool("chat.send", {"message": "synthetic"})

        result = asyncio.run(call())
        assert bool(result.is_error) is not success
        assert result.structured_content["events"] == emitted
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_cli_closes_owned_session_after_stream_completion(monkeypatch):
    client = Mock()
    client.invoke.return_value = iter([{"done": True}])
    monkeypatch.setattr(cli, "VantageClient", lambda *args: client)
    assert cli.main(["chat", "send", "--message", "synthetic"]) == 0
    client.session.close.assert_called_once()

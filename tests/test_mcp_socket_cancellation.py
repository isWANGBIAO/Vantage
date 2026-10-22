"""Cancellation responsiveness with real requests/urllib3 socket locks."""
import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from mcp import Client

from src.mcp_server import create_mcp_server


@pytest.mark.parametrize("mode", ["cancel_stream", "cancel_headers", "normal"])
def test_real_slow_stream_does_not_block_event_loop_on_cancel(mode):
    started = threading.Event()
    finished = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            if not self.path.endswith("/events"):
                body = b'{"status":"ready"}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if mode == "cancel_headers":
                started.set()
                time.sleep(1.5)
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                first = (json.dumps({"log": "synthetic " + "x" * 600}) + "\n").encode()
                self.wfile.write(f"{len(first):x}\r\n".encode() + first + b"\r\n")
                self.wfile.flush()
                started.set()
                if mode != "cancel_headers":
                    time.sleep(1.5)
                final = b'{"done":true}\n'
                self.wfile.write(f"{len(final):x}\r\n".encode() + final + b"\r\n0\r\n\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                finished.set()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    async def exercise():
        async with Client(create_mcp_server(base_url=f"http://127.0.0.1:{server.server_port}")) as client:
            task = asyncio.create_task(client.call_tool("action_plan.jobs.events", {"job_id": "synthetic"}))
            assert await asyncio.to_thread(started.wait, 5)
            await asyncio.sleep(0.1)
            mark = asyncio.Event()
            at = time.monotonic()
            elapsed = []
            asyncio.get_running_loop().call_later(0.05, lambda: (elapsed.append(time.monotonic() - at), mark.set()))
            if mode != "normal":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert time.monotonic() - at < 0.25
                status = await asyncio.wait_for(client.call_tool("system.status.read", {}), 0.25)
                assert not status.is_error
            else:
                result = await task
                assert not result.is_error
            await asyncio.wait_for(mark.wait(), 0.5)
            assert elapsed[0] < 0.25
        assert await asyncio.to_thread(finished.wait, 5)

    try:
        asyncio.run(exercise())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)

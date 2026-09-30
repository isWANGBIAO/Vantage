import asyncio
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import mcp
import requests
import src.mcp_server as mcp_server_module
import src.services.vantage_client as vantage_client_module
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.types import (
    BlobResourceContents,
    CallToolRequestParams,
    EmbeddedResource,
    TextContent,
)

from src.services.automation_catalog import OPERATIONS
from src.services.vantage_client import VantageClient
from src.mcp_server import (
    CATALOG_RESOURCE_URI,
    create_mcp_server,
    operation_resource_uri,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MCP_SITE_PACKAGES = Path(mcp.__file__).resolve().parent.parent


class _Response:
    def __init__(
        self,
        *,
        payload=None,
        status_code=200,
        text="",
        content=b"",
        headers=None,
        lines=None,
    ):
        self.payload = payload
        self.status_code = status_code
        self.text = text
        self.content = content
        self.headers = headers or {"Content-Type": "application/json"}
        self.lines = lines or []
        self.closed = False

    def json(self):
        return self.payload

    def iter_lines(self, decode_unicode=True):
        yield from self.lines

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, response=None, *, error=None):
        self.response = response
        self.error = error
        self.calls = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error is not None:
            raise self.error
        return self.response

    def close(self):
        self.closed = True


def _run(coro):
    return asyncio.run(coro)


def _mcp_client(server):
    return Client(server)


def _server_for_session(session):
    return create_mcp_server(client_factory=lambda: VantageClient(session=session))


def test_every_catalog_operation_is_a_tool_with_identical_schema_and_description():
    async def scenario():
        async with _mcp_client(create_mcp_server()) as client:
            listed = await client.list_tools()

        assert len(listed.tools) == len(OPERATIONS)
        by_name = {tool.name: tool for tool in listed.tools}
        assert set(by_name) == {operation.name for operation in OPERATIONS}
        for operation in OPERATIONS:
            tool = by_name[operation.name]
            assert tool.description == operation.description
            assert tool.input_schema == operation.input_schema

        unavailable = [item for item in OPERATIONS if item.availability != "available"]
        assert unavailable
        assert all(item.name in by_name for item in unavailable)

    _run(scenario())


def test_catalog_and_per_operation_resources_export_static_metadata():
    operation = next(item for item in OPERATIONS if item.name == "system.status.read")

    async def scenario():
        async with _mcp_client(create_mcp_server()) as client:
            listed = await client.list_resources()
            catalog = await client.read_resource(CATALOG_RESOURCE_URI)
            detail = await client.read_resource(operation_resource_uri(operation.name))

        assert len(listed.resources) == len(OPERATIONS) + 1
        assert {resource.uri for resource in listed.resources} == {
            CATALOG_RESOURCE_URI,
            *(operation_resource_uri(item.name) for item in OPERATIONS),
        }
        directory = json.loads(catalog.contents[0].text)
        detail_metadata = json.loads(detail.contents[0].text)
        assert [item["name"] for item in directory["operations"]] == [
            item.name for item in OPERATIONS
        ]
        assert detail_metadata["name"] == operation.name
        assert detail_metadata["description"] == operation.description
        assert detail_metadata["input_schema"] == operation.input_schema

    _run(scenario())


def test_json_backend_result_is_returned_as_text_and_structured_content():
    payload = {"status": "ok", "message": "已就绪 😀"}
    session = _Session(_Response(payload=payload))
    server = _server_for_session(session)

    async def scenario():
        async with _mcp_client(server) as client:
            result = await client.call_tool("system.status.read", {})
        return result

    result = _run(scenario())
    assert result.is_error is False
    assert result.structured_content == payload
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    assert json.loads(result.content[0].text) == payload
    assert "😀" in result.content[0].text
    assert session.calls[0][1].endswith("/api/status")


def test_stream_output_preserves_each_ndjson_event_in_order():
    events = [{"progress": 0.25}, {"progress": 1.0, "done": True}]
    response = _Response(lines=[json.dumps(item) for item in events])
    session = _Session(response)
    server = _server_for_session(session)

    async def scenario():
        async with _mcp_client(server) as client:
            return await client.call_tool("chat.send", {"message": "test"})

    result = _run(scenario())
    assert result.is_error is False
    assert result.structured_content == {"events": events}
    assert [json.loads(line) for line in result.content[0].text.splitlines()] == events
    assert response.closed is True


def test_file_download_is_embedded_as_binary_resource_without_base64_text():
    payload = b"\x00xlsx-binary\xff"
    response = _Response(
        content=payload,
        headers={
            "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "Content-Disposition": 'attachment; filename="face report.xlsx"',
        },
    )
    server = _server_for_session(_Session(response))

    async def scenario():
        async with _mcp_client(server) as client:
            return await client.call_tool("face.export", {})

    result = _run(scenario())
    resource = next(item for item in result.content if isinstance(item, EmbeddedResource))
    assert result.is_error is False
    assert isinstance(resource.resource, BlobResourceContents)
    assert base64.b64decode(resource.resource.blob) == payload
    assert resource.resource.mime_type == response.headers["Content-Type"]
    assert result.structured_content == {
        "filename": "face report.xlsx",
        "content_type": response.headers["Content-Type"],
        "size_bytes": len(payload),
    }
    assert base64.b64encode(payload).decode("ascii") not in "".join(
        getattr(item, "text", "") for item in result.content
    )
    assert response.closed is True


def test_client_schema_validation_is_a_non_leaking_actionable_tool_error():
    secret = "DO_NOT_ECHO_MCP_SECRET_92b3"
    session = _Session(_Response(payload={"unexpected": "must not be requested"}))
    server = _server_for_session(session)

    async def scenario():
        async with _mcp_client(server) as client:
            return await client.call_tool(
                "settings.display_language.update",
                {"display_language": "zh-CN", "api_key": secret},
            )

    result = _run(scenario())
    message = result.content[0].text
    assert result.is_error is True
    assert "api_key" in message
    assert secret not in message
    assert session.calls == []


def test_unavailable_catalog_operation_is_listed_and_returns_its_reason():
    session = _Session(_Response(payload={}))
    server = _server_for_session(session)

    async def scenario():
        async with _mcp_client(server) as client:
            tools = await client.list_tools()
            result = await client.call_tool("settings.open_path", {"path_key": "history"})
        return tools, result

    tools, result = _run(scenario())
    assert "settings.open_path" in {item.name for item in tools.tools}
    assert result.is_error is True
    assert "requires a native platform adapter" in result.content[0].text
    assert session.calls == []


def test_backend_unavailable_error_explains_recovery_without_leaking_transport_detail():
    session = _Session(error=requests.exceptions.ConnectionError("Bearer never-log-this"))
    server = _server_for_session(session)

    async def scenario():
        async with _mcp_client(server) as client:
            return await client.call_tool("system.status.read", {})

    result = _run(scenario())
    message = result.content[0].text
    assert result.is_error is True
    assert "Start Vantage" in message
    assert "does not start another API server" in message
    assert "Bearer never-log-this" not in message


def test_backend_http_error_is_safe_and_actionable():
    server = create_mcp_server(
        VantageClient(session=_Session(_Response(status_code=503)))
    )

    async def scenario():
        async with _mcp_client(server) as client:
            return await client.call_tool("system.status.read", {})

    result = _run(scenario())
    assert result.is_error is True
    assert "HTTP 503" in result.content[0].text
    assert "Vantage logs" in result.content[0].text


def test_blocking_backend_request_does_not_delay_asyncio_timer():
    timer_fired = threading.Event()
    release_request = threading.Event()

    class _BlockingSession(_Session):
        released_by_timer = False

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            self.released_by_timer = release_request.wait(timeout=0.5)
            return _Response(payload={"status": "ready"})

    session = _BlockingSession()
    server = _server_for_session(session)

    async def scenario():
        loop = asyncio.get_running_loop()

        def release_from_loop():
            timer_fired.set()
            release_request.set()

        loop.call_later(0.01, release_from_loop)
        handler = server.get_request_handler("tools/call").handler
        return await handler(
            None,
            CallToolRequestParams(name="system.status.read", arguments={}),
        )

    result = _run(scenario())
    assert result.is_error is False
    assert session.released_by_timer is True
    assert timer_fired.is_set()


def test_parallel_operations_use_independent_http_sessions(monkeypatch):
    barrier = threading.Barrier(2)
    sessions = []

    class _ConcurrentSession(_Session):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            barrier.wait(timeout=5)
            return _Response(payload={"status": "ready"})

    def new_session():
        session = _ConcurrentSession()
        sessions.append(session)
        return session

    monkeypatch.setattr(vantage_client_module.requests, "Session", new_session)
    server = create_mcp_server(base_url="http://127.0.0.1:8000")

    async def scenario():
        async with _mcp_client(server) as client:
            return await asyncio.gather(
                client.call_tool("system.status.read", {}),
                client.call_tool("system.status.read", {}),
            )

    results = _run(scenario())
    assert all(result.is_error is False for result in results)
    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]
    assert all(session.closed for session in sessions)


def test_production_mcp_client_uses_long_enough_timeout_for_face_export(monkeypatch):
    response = _Response(
        content=b"workbook",
        headers={"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    )
    session = _Session(response)
    monkeypatch.setattr(vantage_client_module.requests, "Session", lambda: session)
    server = create_mcp_server(base_url="http://127.0.0.1:8000")

    async def scenario():
        async with _mcp_client(server) as client:
            return await client.call_tool("face.export", {})

    result = _run(scenario())
    assert result.is_error is False
    timeout_seconds = getattr(mcp_server_module, "MCP_OPERATION_TIMEOUT_SECONDS", 0)
    assert timeout_seconds >= 90
    assert session.calls[0][2]["timeout"] == timeout_seconds
    assert response.closed is True
    assert session.closed is True


def test_stream_error_closes_response_and_session_without_leaking_transport_detail():
    secret = "Bearer stream-secret-4e5a"

    class _BrokenStreamResponse(_Response):
        def iter_lines(self, decode_unicode=True):
            yield json.dumps({"progress": 0.2})
            raise requests.exceptions.ConnectionError(secret)

    response = _BrokenStreamResponse()
    session = _Session(response)
    server = _server_for_session(session)

    async def scenario():
        async with _mcp_client(server) as client:
            return await client.call_tool("chat.send", {"message": "test"})

    result = _run(scenario())
    assert result.is_error is True
    assert "connection was interrupted" in result.content[0].text
    assert secret not in result.content[0].text
    assert response.closed is True
    assert session.closed is True


def test_cancelling_blocked_stream_closes_response_and_session_immediately(monkeypatch):
    stream_started = threading.Event()
    release_stream = threading.Event()
    worker_finished = threading.Event()
    worker_settled = asyncio.Event()
    invoke_and_convert = mcp_server_module._invoke_and_convert
    consume_worker_result = mcp_server_module._consume_worker_result

    def track_worker_completion(*args, **kwargs):
        try:
            return invoke_and_convert(*args, **kwargs)
        finally:
            worker_finished.set()

    monkeypatch.setattr(mcp_server_module, "_invoke_and_convert", track_worker_completion)

    def track_worker_settled(worker):
        consume_worker_result(worker)
        worker_settled.set()

    monkeypatch.setattr(mcp_server_module, "_consume_worker_result", track_worker_settled)

    class _BlockingResponse(_Response):
        def iter_lines(self, decode_unicode=True):
            stream_started.set()
            if not release_stream.wait(timeout=5):
                raise TimeoutError("test stream was not released")
            yield json.dumps({"progress": 1.0})
            raise requests.exceptions.ConnectionError("cancelled stream failure")

        def close(self):
            super().close()
            release_stream.set()

    response = _BlockingResponse()
    session = _Session(response)
    server = _server_for_session(session)
    handler = server.get_request_handler("tools/call").handler

    async def scenario():
        loop = asyncio.get_running_loop()
        unhandled = []
        previous_exception_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
        task = asyncio.create_task(
            handler(None, CallToolRequestParams(name="chat.send", arguments={"message": "test"}))
        )
        try:
            assert await asyncio.wait_for(asyncio.to_thread(stream_started.wait, 1), timeout=2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("the MCP handler should propagate cancellation")

            assert response.closed is True
            assert session.closed is True
            assert await asyncio.wait_for(asyncio.to_thread(worker_finished.wait, 1), timeout=2)
            # A thread's finally runs before to_thread's Future and its done
            # callbacks settle on the loop. One sleep(0) is not a synchronization
            # barrier on Windows/Python 3.13. Wait for the real cleanup callback
            # without gathering the worker ourselves (which would mask a missing
            # exception-consumption callback).
            await asyncio.wait_for(worker_settled.wait(), timeout=2)
            assert not [
                pending
                for pending in asyncio.all_tasks()
                if pending is not asyncio.current_task() and not pending.done()
            ]
            assert unhandled == []
        finally:
            loop.set_exception_handler(previous_exception_handler)
            release_stream.set()
            if not task.done():
                task.cancel()
            await asyncio.wait_for(asyncio.to_thread(worker_finished.wait, 1), timeout=2)

    _run(scenario())


def test_cancellation_before_stream_result_attaches_closes_late_result(monkeypatch):
    request_started = threading.Event()
    release_request = threading.Event()
    stream_started = threading.Event()
    response_closed = threading.Event()
    worker_finished = threading.Event()
    invoke_and_convert = mcp_server_module._invoke_and_convert

    def track_worker_completion(*args, **kwargs):
        try:
            return invoke_and_convert(*args, **kwargs)
        finally:
            worker_finished.set()

    monkeypatch.setattr(mcp_server_module, "_invoke_and_convert", track_worker_completion)

    class _LateResponse(_Response):
        def iter_lines(self, decode_unicode=True):
            stream_started.set()
            yield json.dumps({"progress": 1.0})

        def close(self):
            super().close()
            response_closed.set()

    class _DelayedSession(_Session):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            request_started.set()
            if not release_request.wait(timeout=5):
                raise TimeoutError("test request was not released")
            return response

        def close(self):
            super().close()
            release_request.set()

    response = _LateResponse()
    session = _DelayedSession()
    server = _server_for_session(session)
    handler = server.get_request_handler("tools/call").handler

    async def scenario():
        task = asyncio.create_task(
            handler(None, CallToolRequestParams(name="chat.send", arguments={"message": "test"}))
        )
        try:
            assert await asyncio.wait_for(asyncio.to_thread(request_started.wait, 1), timeout=2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("the MCP handler should propagate cancellation")

            assert session.closed is True
            assert await asyncio.wait_for(asyncio.to_thread(response_closed.wait, 1), timeout=2)
            assert response.closed is True
            assert stream_started.is_set() is False
            assert await asyncio.wait_for(asyncio.to_thread(worker_finished.wait, 1), timeout=2)
            await asyncio.sleep(0)
            assert not [
                pending
                for pending in asyncio.all_tasks()
                if pending is not asyncio.current_task() and not pending.done()
            ]
        finally:
            release_request.set()
            if not task.done():
                task.cancel()
            await asyncio.wait_for(asyncio.to_thread(worker_finished.wait, 1), timeout=2)

    _run(scenario())


def test_stdio_startup_fails_cleanly_when_backend_is_down():
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.cli",
            "--base-url",
            "http://127.0.0.1:1",
            "mcp",
        ],
        cwd=REPOSITORY_ROOT,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                (os.fspath(REPOSITORY_ROOT), os.fspath(MCP_SITE_PACKAGES))
            ),
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )

    assert completed.returncode == 3
    assert completed.stdout == ""
    assert "Vantage backend is unavailable" in completed.stderr
    assert "Start Vantage" in completed.stderr
    assert "does not start another API server" in completed.stderr


def test_real_stdio_subprocess_round_trip_keeps_stdout_protocol_clean():
    class _StatusHandler(BaseHTTPRequestHandler):
        calls = []

        def do_GET(self):
            type(self).calls.append(self.path)
            body = json.dumps({"status": "ready", "message": "stdio works"}).encode(
                "utf-8"
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    backend = ThreadingHTTPServer(("127.0.0.1", 0), _StatusHandler)
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    backend_url = f"http://127.0.0.1:{backend.server_port}"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "src.cli",
            "--base-url",
            backend_url,
            "mcp",
        ],
        cwd=REPOSITORY_ROOT,
        env={
            "PYTHONPATH": os.pathsep.join(
                (os.fspath(REPOSITORY_ROOT), os.fspath(MCP_SITE_PACKAGES))
            )
        },
        encoding="utf-8",
    )

    try:
        async def scenario():
            async with Client(parameters) as client:
                tools = await client.list_tools()
                result = await client.call_tool("system.status.read", {})
            return tools, result

        tools, result = _run(scenario())
    finally:
        backend.shutdown()
        backend.server_close()
        thread.join(timeout=5)

    assert "system.status.read" in {item.name for item in tools.tools}
    assert result.is_error is False
    assert result.structured_content == {"status": "ready", "message": "stdio works"}
    assert _StatusHandler.calls == ["/api/status", "/api/status"]

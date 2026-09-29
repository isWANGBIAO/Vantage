"""MCP stdio adapter for Vantage's shared product-operation catalog."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote, unquote

import mcp.types as types
import requests
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server

from src.services.automation_catalog import OPERATIONS, Operation, get_operation
from src.services.vantage_client import (
    ArgumentValidationError,
    BackendHTTPError,
    BackendUnavailableError,
    FileDownload,
    OperationUnavailableError,
    VantageClient,
    VantageClientError,
)


LOGGER = logging.getLogger(__name__)
CATALOG_RESOURCE_URI = "vantage://catalog"
OPERATION_RESOURCE_PREFIX = "vantage://operations/"
DOWNLOAD_RESOURCE_PREFIX = "vantage://downloads/"
MCP_OPERATION_TIMEOUT_SECONDS = 90.0
_OPERATIONS_BY_NAME = {operation.name: operation for operation in OPERATIONS}


def operation_resource_uri(name: str) -> str:
    """Return the stable static-resource URI for one catalog operation."""

    return f"{OPERATION_RESOURCE_PREFIX}{quote(name, safe='.')}"


def _json_value(value: Any) -> Any:
    """Copy immutable catalog values into ordinary JSON-compatible containers."""

    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _operation_metadata(operation: Operation) -> dict[str, Any]:
    return {
        "name": operation.name,
        "description": operation.description,
        "input_schema": _json_value(operation.input_schema),
        "output_kind": operation.output_kind,
        "availability": operation.availability,
        "unavailable_reason": operation.unavailable_reason,
        "mutation": operation.mutation,
        "side_effect": operation.side_effect,
        "sensitive": operation.sensitive,
        "stream": operation.stream,
        "download": operation.download,
    }


def _catalog_payload() -> dict[str, Any]:
    return {
        "format_version": 1,
        "name": "Vantage",
        "operations": [_operation_metadata(operation) for operation in OPERATIONS],
    }


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _error_result(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=message)],
        is_error=True,
    )


def _backend_http_message(error: BackendHTTPError) -> str:
    if error.status_code >= 500:
        return (
            f"{error} Check that Vantage is running and responsive. If the problem persists, "
            "inspect the Vantage logs and retry."
        )
    return (
        f"{error} Check the operation inputs and current Vantage state, then retry."
    )


def _verify_backend_ready(client: VantageClient) -> None:
    """Fail before opening stdio if the existing backend cannot serve requests."""

    try:
        client.invoke("system.status.read", {})
    except BackendUnavailableError:
        raise BackendUnavailableError(
            "Vantage backend is unavailable. Start Vantage and retry. The MCP server "
            "reuses the desktop application's existing backend and does not start another "
            "API server."
        ) from None
    except BackendHTTPError as error:
        raise BackendHTTPError(
            error.status_code,
            f"{_backend_http_message(error)} Ensure Vantage is already running before "
            "starting its MCP server.",
        ) from None
    except VantageClientError:
        raise VantageClientError(
            "Unable to verify Vantage backend readiness. Confirm Vantage is running and "
            "inspect its logs, then retry."
        ) from None


def _consume_stream(stream: Any) -> list[Any]:
    events: list[Any] = []
    try:
        events.extend(stream)
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    return events


def _download_result(download: FileDownload) -> types.CallToolResult:
    filename = download.filename or "download.bin"
    mime_type = download.content_type or "application/octet-stream"
    resource_uri = f"{DOWNLOAD_RESOURCE_PREFIX}{quote(filename, safe='')}"
    summary = {
        "filename": filename,
        "content_type": mime_type,
        "size_bytes": len(download.content),
    }
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=f"Downloaded {filename} ({len(download.content)} bytes).",
            ),
            types.EmbeddedResource(
                resource=types.BlobResourceContents(
                    uri=resource_uri,
                    mime_type=mime_type,
                    blob=base64.b64encode(download.content).decode("ascii"),
                )
            ),
        ],
        structured_content=summary,
    )


def _success_result(operation: Operation, result: Any) -> types.CallToolResult:
    if operation.stream:
        events = _consume_stream(result)
        ndjson = "\n".join(
            json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            for event in events
        )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=ndjson)],
            structured_content={"events": events},
        )

    if operation.download:
        if not isinstance(result, FileDownload):
            return _error_result(
                "Vantage returned an invalid file response; check the backend logs and retry."
            )
        return _download_result(result)

    if operation.output_kind == "text":
        if not isinstance(result, str):
            return _error_result(
                "Vantage returned an invalid text response; check the backend logs and retry."
            )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=result)]
        )

    if operation.output_kind == "json":
        structured = (
            _json_value(result)
            if isinstance(result, Mapping)
            else {"result": _json_value(result)}
        )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=_json_text(result))],
            structured_content=structured,
        )

    return _error_result(
        "Vantage returned an unsupported response type; check the backend logs and retry."
    )


def _close_safely(value: Any, resource_name: str) -> None:
    close = getattr(value, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception as error:
        LOGGER.debug(
            "Unable to close MCP %s (%s).",
            resource_name,
            type(error).__name__,
        )


def _close_client_session(client: VantageClient) -> None:
    _close_safely(getattr(client, "session", None), "backend session")


class _MCPCallState:
    """Synchronize cancellation with resources created by a worker thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled = False
        self._client: VantageClient | None = None
        self._result: Any = None

    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def attach_client(self, client: VantageClient) -> bool:
        with self._lock:
            cancelled = self._cancelled
            if not cancelled:
                self._client = client
        if cancelled:
            _close_client_session(client)
            return False
        return True

    def attach_result(self, result: Any) -> bool:
        with self._lock:
            cancelled = self._cancelled
            if not cancelled:
                self._result = result
        if cancelled:
            _close_safely(result, "backend result")
            return False
        return True

    def close_resources(self, *, cancelled: bool = False) -> None:
        with self._lock:
            if cancelled:
                self._cancelled = True
            result, self._result = self._result, None
            client, self._client = self._client, None

        _close_safely(result, "backend result")
        if client is not None:
            _close_client_session(client)


def _consume_worker_result(task: asyncio.Task[Any]) -> None:
    """Retrieve late worker failures after the MCP request has been cancelled."""

    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception as error:
        LOGGER.debug(
            "Cancelled MCP operation worker ended with %s.",
            type(error).__name__,
        )


def _invoke_and_convert(
    client_factory: Callable[[], VantageClient],
    operation: Operation,
    arguments: Mapping[str, Any],
    call_state: _MCPCallState,
) -> types.CallToolResult:
    """Run the synchronous HTTP call and consume/convert its result off-loop."""

    if call_state.is_cancelled():
        return _error_result("The Vantage operation was cancelled.")

    client = client_factory()
    if not call_state.attach_client(client):
        return _error_result("The Vantage operation was cancelled.")
    try:
        result = client.invoke(operation, arguments)
        if not call_state.attach_result(result):
            return _error_result("The Vantage operation was cancelled.")
        return _success_result(operation, result)
    finally:
        call_state.close_resources()


def create_mcp_server(
    vantage_client: VantageClient | None = None,
    *,
    base_url: str | None = None,
    client_factory: Callable[[], VantageClient] | None = None,
) -> Server:
    """Create a catalog MCP server; production uses fresh clients per tool call."""

    if client_factory is not None and vantage_client is not None:
        raise ValueError("Pass either vantage_client or client_factory, not both.")
    if vantage_client is not None and base_url is not None:
        raise ValueError("Pass either vantage_client or base_url, not both.")
    if client_factory is not None:
        operation_client_factory = client_factory
    elif vantage_client is not None:
        operation_client_factory = lambda: vantage_client
    else:
        operation_client_factory = lambda: VantageClient(
            base_url,
            timeout=MCP_OPERATION_TIMEOUT_SECONDS,
        )

    async def list_tools(
        _context: ServerRequestContext,
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=operation.name,
                    description=operation.description,
                    input_schema=_json_value(operation.input_schema),
                )
                for operation in OPERATIONS
            ]
        )

    async def call_tool(
        _context: ServerRequestContext,
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        operation = _OPERATIONS_BY_NAME.get(params.name)
        if operation is None:
            return _error_result("Unknown Vantage operation. Refresh the catalog and retry.")

        call_state = _MCPCallState()
        worker = asyncio.create_task(
            asyncio.to_thread(
                _invoke_and_convert,
                operation_client_factory,
                operation,
                params.arguments or {},
                call_state,
            ),
            name=f"vantage-mcp-{operation.name}",
        )
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            call_state.close_resources(cancelled=True)
            worker.add_done_callback(_consume_worker_result)
            raise
        except OperationUnavailableError as error:
            return _error_result(str(error))
        except ArgumentValidationError as error:
            return _error_result(str(error))
        except BackendUnavailableError:
            return _error_result(
                "Vantage backend is unavailable. Start Vantage and retry. This MCP server "
                "reuses the desktop application's existing backend and does not start another "
                "API server."
            )
        except BackendHTTPError as error:
            return _error_result(_backend_http_message(error))
        except requests.exceptions.RequestException:
            return _error_result(
                "The Vantage connection was interrupted. Confirm the backend is healthy and retry."
            )
        except VantageClientError as error:
            return _error_result(str(error))
        except Exception as error:  # Keep implementation details and arguments out of MCP output.
            LOGGER.error(
                "Unexpected MCP operation failure: %s (%s).",
                operation.name,
                type(error).__name__,
            )
            return _error_result(
                "Vantage could not complete this operation due to an internal error. "
                "Check the Vantage logs and retry."
            )
        finally:
            call_state.close_resources()

    async def list_resources(
        _context: ServerRequestContext,
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListResourcesResult:
        resources = [
            types.Resource(
                uri=CATALOG_RESOURCE_URI,
                name="Vantage capability catalog",
                description="Static directory of product operations and their schemas.",
                mime_type="application/json",
            )
        ]
        resources.extend(
            types.Resource(
                uri=operation_resource_uri(operation.name),
                name=operation.name,
                description=operation.description,
                mime_type="application/json",
            )
            for operation in OPERATIONS
        )
        return types.ListResourcesResult(resources=resources)

    async def read_resource(
        _context: ServerRequestContext,
        params: types.ReadResourceRequestParams,
    ) -> types.ReadResourceResult:
        uri = str(params.uri)
        if uri == CATALOG_RESOURCE_URI:
            payload = _catalog_payload()
        elif uri.startswith(OPERATION_RESOURCE_PREFIX):
            name = unquote(uri.removeprefix(OPERATION_RESOURCE_PREFIX))
            try:
                operation = get_operation(name)
            except KeyError:
                raise ValueError("Unknown Vantage catalog resource.") from None
            payload = _operation_metadata(operation)
        else:
            raise ValueError("Unknown Vantage catalog resource.")

        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=uri,
                    mime_type="application/json",
                    text=_json_text(payload),
                )
            ]
        )

    return Server(
        "Vantage",
        instructions=(
            "Use the catalog resources to discover Vantage operations and their exact input schemas. "
            "Operations are executed only through the already-running local Vantage backend."
        ),
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_list_resources=list_resources,
        on_read_resource=read_resource,
    )


def run_stdio(base_url: str | None = None) -> None:
    """Run the catalog server using MCP's stdio transport (stdout is protocol-only)."""

    client = VantageClient(base_url)
    try:
        _verify_backend_ready(client)
    finally:
        client.session.close()
    server = create_mcp_server(base_url=client.base_url)

    async def serve() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    asyncio.run(serve())


if __name__ == "__main__":
    run_stdio()

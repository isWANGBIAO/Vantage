"""Shared HTTP client for catalogued Vantage operations.

The client deliberately owns transport and input-shape validation only. Product
behavior stays in the existing backend endpoints; CLI and MCP callers share
this adapter rather than reimplementing those rules.
"""

from __future__ import annotations

import json
import ipaddress
import math
import mimetypes
import re
from contextlib import ExitStack
from dataclasses import dataclass
from email.message import Message
from email.utils import collapse_rfc2231_value
from pathlib import Path
from typing import Any, Iterator, Mapping
from urllib.parse import quote, unquote, urlsplit

import requests

from src.services.automation_catalog import Operation, get_operation


DEFAULT_BACKEND_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 30.0
_PATH_PARAMETER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_UNSAFE_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class VantageClientError(Exception):
    """Base class for safe, user-facing client failures."""


class UnknownOperationError(VantageClientError):
    """Raised when the requested operation is not in the shared catalog."""


class OperationUnavailableError(VantageClientError):
    """Raised when an operation still requires an Electron/backend bridge."""


class ArgumentValidationError(VantageClientError):
    """Raised when arguments do not match the catalog JSON Schema subset."""


class BackendUnavailableError(VantageClientError):
    """Raised when the local Vantage backend cannot be reached."""


class BackendHTTPError(VantageClientError):
    """Raised for non-success responses without exposing server/request data."""

    def __init__(self, status_code: int, message: str | None = None):
        self.status_code = status_code
        super().__init__(message or f"Vantage backend returned HTTP {status_code}.")


class BackendRedirectError(BackendHTTPError):
    """Raised when the local backend attempts an HTTP redirect."""

    def __init__(self, status_code: int):
        super().__init__(
            status_code,
            f"Vantage backend returned an unsupported HTTP {status_code} response; "
            "redirects are not followed for security.",
        )


class BackendProtocolError(VantageClientError):
    """Raised when a successful response does not match its catalog format."""


@dataclass(frozen=True, slots=True)
class FileDownload:
    """Downloaded bytes with a basename safe to write inside a chosen folder."""

    filename: str
    content: bytes
    content_type: str | None = None


class NDJSONStream(Iterator[Any]):
    """Lazy decoded NDJSON response iterator that closes its HTTP response."""

    def __init__(self, response):
        self._response = response
        self._lines = iter(response.iter_lines(decode_unicode=True))
        self._closed = False

    def __iter__(self) -> "NDJSONStream":
        return self

    def __next__(self) -> Any:
        if self._closed:
            raise StopIteration
        try:
            for line in self._lines:
                if isinstance(line, bytes):
                    line = line.decode("utf-8")
                if not line or not line.strip():
                    continue
                try:
                    return json.loads(line)
                except (TypeError, ValueError):
                    self.close()
                    raise BackendProtocolError(
                        "Vantage backend returned an invalid NDJSON stream."
                    ) from None
            self.close()
            raise StopIteration
        except UnicodeDecodeError:
            self.close()
            raise BackendProtocolError(
                "Vantage backend returned an invalid NDJSON stream."
            ) from None
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._response.close()

    def __enter__(self) -> "NDJSONStream":
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()

    def __del__(self):
        self.close()


def _path_label(path: str) -> str:
    return "arguments" if path == "$" else path.removeprefix("$.")


def _matches_json_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and (isinstance(value, int) or math.isfinite(value))
        )
    if expected == "null":
        return value is None
    return False


def _enum_contains(value: Any, choices: list[Any] | tuple[Any, ...]) -> bool:
    for choice in choices:
        if isinstance(value, bool) or isinstance(choice, bool):
            if type(value) is type(choice) and value == choice:
                return True
        elif isinstance(value, (int, float)) and isinstance(choice, (int, float)):
            if not isinstance(value, bool) and not isinstance(choice, bool) and value == choice:
                return True
        elif type(value) is type(choice) and value == choice:
            return True
    return False


def _validate_schema(value: Any, schema: Mapping[str, Any], path: str = "$") -> None:
    """Validate the JSON Schema features used by the operation catalog."""

    expected_type = schema.get("type")
    if expected_type:
        expected_types = (
            tuple(expected_type) if isinstance(expected_type, (list, tuple)) else (expected_type,)
        )
        if not any(_matches_json_type(value, item) for item in expected_types):
            label = _path_label(path)
            expected = " or ".join(expected_types)
            raise ArgumentValidationError(f"{label} must be {expected}.")

    if "const" in schema and not _enum_contains(value, [schema["const"]]):
        raise ArgumentValidationError(f"{_path_label(path)} must match the required value.")

    if "enum" in schema and not _enum_contains(value, schema["enum"]):
        raise ArgumentValidationError(f"{_path_label(path)} must be one of the allowed values.")

    all_of = schema.get("allOf")
    if all_of:
        for branch in all_of:
            if isinstance(branch, Mapping):
                _validate_schema(value, branch, path)

    one_of = schema.get("oneOf")
    if one_of:
        matching_schemas = 0
        for branch in one_of:
            if not isinstance(branch, Mapping):
                continue
            try:
                _validate_schema(value, branch, path)
            except ArgumentValidationError:
                continue
            matching_schemas += 1
        if matching_schemas != 1:
            raise ArgumentValidationError(
                f"{_path_label(path)} must match exactly one allowed schema."
            )

    condition = schema.get("if")
    if isinstance(condition, Mapping):
        try:
            _validate_schema(value, condition, path)
        except ArgumentValidationError:
            branch = schema.get("else")
        else:
            branch = schema.get("then")
        if isinstance(branch, Mapping):
            _validate_schema(value, branch, path)

    if isinstance(value, Mapping):
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            properties = {}
        for required_name in schema.get("required", ()):
            if required_name not in value:
                raise ArgumentValidationError(
                    f"{_path_label(path)}.{required_name} is required."
                )
        additional = schema.get("additionalProperties", True)
        for key, child_value in value.items():
            child_schema = properties.get(key)
            child_path = f"{path}.{key}"
            if child_schema is not None:
                _validate_schema(child_value, child_schema, child_path)
            elif additional is False:
                raise ArgumentValidationError(f"{_path_label(child_path)} is not allowed.")
            elif isinstance(additional, Mapping):
                _validate_schema(child_value, additional, child_path)
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            raise ArgumentValidationError(f"{_path_label(path)} has too few properties.")
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            raise ArgumentValidationError(f"{_path_label(path)} has too many properties.")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise ArgumentValidationError(f"{_path_label(path)} has too few items.")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ArgumentValidationError(f"{_path_label(path)} has too many items.")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                _validate_schema(item, item_schema, f"{path}[{index}]")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise ArgumentValidationError(f"{_path_label(path)} is too short.")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise ArgumentValidationError(f"{_path_label(path)} is too long.")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise ArgumentValidationError(f"{_path_label(path)} has an invalid format.")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise ArgumentValidationError(f"{_path_label(path)} must be a finite number.")
        if "minimum" in schema and value < schema["minimum"]:
            raise ArgumentValidationError(f"{_path_label(path)} must be at least {schema['minimum']}.")
        if "maximum" in schema and value > schema["maximum"]:
            raise ArgumentValidationError(f"{_path_label(path)} must be at most {schema['maximum']}.")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            raise ArgumentValidationError(
                f"{_path_label(path)} must be greater than {schema['exclusiveMinimum']}."
            )
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            raise ArgumentValidationError(
                f"{_path_label(path)} must be less than {schema['exclusiveMaximum']}."
            )


def _filename_from_headers(headers: Mapping[str, Any]) -> str:
    disposition = headers.get("Content-Disposition", "") or headers.get(
        "content-disposition", ""
    )
    message = Message()
    message["content-disposition"] = str(disposition)
    filename = message.get_filename()
    if isinstance(filename, tuple):
        filename = collapse_rfc2231_value(filename)
    if not filename:
        extended_match = re.search(r"(?:^|;)\s*filename\*\s*=\s*([^;]+)", str(disposition), re.I)
        if extended_match:
            encoded = extended_match.group(1).strip().strip('"')
            _charset, _language, separator, encoded_name = encoded.partition("''")
            filename = unquote(encoded_name if separator else encoded)
    if not filename:
        filename = "download.bin"

    # Treat both POSIX and Windows path separators as directories, regardless
    # of the OS running this CLI/MCP process.
    basename = str(filename).replace("\\", "/").rsplit("/", 1)[-1]
    basename = _UNSAFE_FILENAME_CHARACTERS.sub("_", basename).strip().rstrip(". ")
    if not basename or basename in {".", ".."}:
        basename = "download.bin"
    stem = basename.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED_FILENAMES:
        basename = f"_{basename}"
    return basename


class VantageClient:
    """Dispatch one catalog operation to the local Vantage HTTP backend."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        session=None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.base_url = self._normalize_base_url(base_url or DEFAULT_BACKEND_BASE_URL)
        self.session = session if session is not None else requests.Session()
        self.timeout = timeout

    @staticmethod
    def _normalize_base_url(value: str) -> str:
        selected_url = value.strip().rstrip("/")
        try:
            parsed = urlsplit(selected_url)
            hostname = parsed.hostname
            # Accessing .port validates malformed port strings.
            _ = parsed.port
        except ValueError:
            raise ValueError("Vantage backend URL must be a valid loopback URL.") from None

        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Vantage backend URL must use HTTP or HTTPS.")
        if not hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Vantage backend URL must be a valid loopback URL.")
        is_loopback = hostname.lower() == "localhost"
        if not is_loopback:
            try:
                is_loopback = ipaddress.ip_address(hostname).is_loopback
            except ValueError:
                is_loopback = False
        if not is_loopback:
            raise ValueError("Vantage backend URL must use a loopback host.")
        return selected_url

    def invoke(
        self,
        operation: str | Operation,
        arguments: Mapping[str, Any] | None = None,
    ) -> Any:
        """Execute the catalog operation and return its declared output shape."""

        descriptor = self._resolve_operation(operation)
        if descriptor.availability != "available":
            reason = descriptor.unavailable_reason or "This operation has no available backend bridge."
            raise OperationUnavailableError(f"{descriptor.name} is unavailable: {reason}")
        if not descriptor.dispatchable or descriptor.dispatch_kind != "http":
            raise OperationUnavailableError(
                f"{descriptor.name} has no available HTTP backend target."
            )

        if arguments is None:
            arguments = {}
        if not isinstance(arguments, Mapping):
            raise ArgumentValidationError("arguments must be an object.")
        copied_arguments = dict(arguments)
        _validate_schema(copied_arguments, descriptor.input_schema)

        url, path_parameters = self._build_url(descriptor, copied_arguments)
        request_arguments = {
            key: value for key, value in copied_arguments.items() if key not in path_parameters
        }
        headers = dict(descriptor.required_headers)

        with ExitStack() as stack:
            request_kwargs: dict[str, Any] = {"timeout": self.timeout}
            if headers:
                request_kwargs["headers"] = headers
            if descriptor.stream or descriptor.download:
                request_kwargs["stream"] = True

            if descriptor.request_media_type == "multipart/form-data":
                data = dict(request_arguments)
                files = {}
                for argument_name, field_name in descriptor.multipart_file_fields.items():
                    if argument_name not in data:
                        continue
                    source_path = Path(data.pop(argument_name))
                    try:
                        file_handle = stack.enter_context(source_path.open("rb"))
                    except OSError:
                        raise VantageClientError(
                            "Unable to read the local file for this Vantage operation."
                        ) from None
                    content_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
                    files[field_name] = (source_path.name or "upload.bin", file_handle, content_type)
                request_kwargs["data"] = data
                request_kwargs["files"] = files
            elif descriptor.method == "GET":
                if request_arguments:
                    request_kwargs["params"] = request_arguments
            elif request_arguments or descriptor.method in {"POST", "PUT", "PATCH"}:
                request_kwargs["json"] = request_arguments

            response = self._send(descriptor, url, request_kwargs)

        if descriptor.stream:
            return NDJSONStream(response)
        if descriptor.download:
            try:
                return FileDownload(
                    filename=_filename_from_headers(response.headers),
                    content=response.content,
                    content_type=response.headers.get("Content-Type")
                    or response.headers.get("content-type"),
                )
            finally:
                response.close()
        try:
            if descriptor.output_kind == "text":
                return response.text
            if descriptor.output_kind == "json":
                try:
                    return response.json()
                except (TypeError, ValueError):
                    raise BackendProtocolError(
                        "Vantage backend returned an invalid JSON response."
                    ) from None
            return response.content
        finally:
            response.close()

    def _resolve_operation(self, operation: str | Operation) -> Operation:
        if isinstance(operation, Operation):
            return operation
        if not isinstance(operation, str):
            raise UnknownOperationError("Vantage operation must be a catalog name or Operation.")
        try:
            return get_operation(operation)
        except KeyError:
            raise UnknownOperationError(f"Unknown Vantage operation: {operation}.") from None

    def _build_url(
        self, operation: Operation, arguments: Mapping[str, Any]
    ) -> tuple[str, set[str]]:
        path = operation.path or ""
        path_parameters = set(_PATH_PARAMETER.findall(path))
        missing = path_parameters - set(arguments)
        if missing:
            name = sorted(missing)[0]
            raise ArgumentValidationError(f"arguments.{name} is required by the operation path.")
        path = _PATH_PARAMETER.sub(
            lambda match: quote(str(arguments[match.group(1)]), safe=""), path
        )
        return f"{self.base_url}{path}", path_parameters

    def _send(self, operation: Operation, url: str, request_kwargs: dict[str, Any]):
        try:
            response = self.session.request(
                operation.method,
                url,
                allow_redirects=False,
                **request_kwargs,
            )
        except requests.exceptions.RequestException:
            raise BackendUnavailableError(
                "Vantage backend is unavailable. Start Vantage and try again."
            ) from None

        status_code = getattr(response, "status_code", 200)
        if 300 <= status_code < 400:
            response.close()
            raise BackendRedirectError(status_code)
        if status_code >= 400:
            response.close()
            raise BackendHTTPError(status_code)
        return response

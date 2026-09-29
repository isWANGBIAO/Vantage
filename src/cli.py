"""Catalog-driven command-line interface for Vantage."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

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


EXIT_OK = 0
EXIT_INPUT_ERROR = 2
EXIT_BACKEND_UNAVAILABLE = 3
EXIT_BACKEND_HTTP_ERROR = 4
EXIT_UNAVAILABLE = 5
EXIT_CLIENT_ERROR = 6
EXIT_OUTPUT_ERROR = 7

_DOWNLOAD_OPTION_NAMES = {"--output"}


class _CliArgumentParser(argparse.ArgumentParser):
    """Argparse variant that never repeats a rejected argument value."""

    def error(self, _message: str) -> None:
        raise _UsageError


class _UsageError(Exception):
    pass


class _InputError(Exception):
    pass


class _OutputError(Exception):
    pass


@dataclass
class _CommandNode:
    children: dict[str, "_CommandNode"] = field(default_factory=dict)
    operation: Operation | None = None


def command_path_for_operation(operation: Operation | str) -> tuple[str, ...]:
    """Map a stable dotted catalog name to its user-facing CLI path."""

    name = operation.name if isinstance(operation, Operation) else operation
    return tuple(segment.replace("_", "-") for segment in name.split("."))


def _command_tree() -> _CommandNode:
    root = _CommandNode()
    for operation in OPERATIONS:
        node = root
        path = command_path_for_operation(operation)
        for segment in path:
            node = node.children.setdefault(segment, _CommandNode())
        if node.operation is not None:
            raise ValueError(f"duplicate CLI command for catalog operation {operation.name}")
        if node.children:
            raise ValueError(f"CLI command collides with an operation group: {operation.name}")
        node.operation = operation
    return root


def _descendant_operations(node: _CommandNode):
    if node.operation is not None:
        yield node.operation
    for child in node.children.values():
        yield from _descendant_operations(child)


def _group_help(node: _CommandNode) -> str:
    operations = tuple(_descendant_operations(node))
    if not operations:
        return "Vantage product operations."
    return operations[0].description.splitlines()[0]


def _operation_help(operation: Operation) -> str:
    description = operation.description.splitlines()[0]
    if operation.availability != "available":
        reason = operation.unavailable_reason or "No backend bridge is available."
        return f"{description} (unavailable: {reason})"
    return description


def _schema_types(schema: Mapping[str, Any]) -> tuple[str, ...]:
    declared = schema.get("type")
    if isinstance(declared, str):
        return (declared,)
    if isinstance(declared, (list, tuple)):
        return tuple(item for item in declared if isinstance(item, str))
    return ()


def _schema_metavar(schema: Mapping[str, Any]) -> str:
    types = _schema_types(schema)
    if "object" in types:
        return "JSON_OBJECT"
    if "array" in types:
        return "JSON_ARRAY"
    if "boolean" in types:
        return "BOOL"
    if "integer" in types:
        return "INTEGER"
    if "number" in types:
        return "NUMBER"
    if "null" in types:
        return "VALUE_OR_NULL"
    return "VALUE"


def _schema_contains_write_only(schema: Any) -> bool:
    if isinstance(schema, Mapping):
        if schema.get("writeOnly") is True:
            return True
        return any(_schema_contains_write_only(value) for value in schema.values())
    if isinstance(schema, (list, tuple)):
        return any(_schema_contains_write_only(value) for value in schema)
    return False


def _schema_option_help(name: str, schema: Mapping[str, Any], *, required: bool) -> str:
    description = str(schema.get("description", "Catalog-defined operation input."))
    enum = schema.get("enum")
    if isinstance(enum, (list, tuple)) and enum:
        description += " Allowed values: " + ", ".join(str(item) for item in enum) + "."
    if required:
        description += " Required."
    if _schema_contains_write_only(schema):
        description += (
            " Sensitive; direct command-line values may be stored in shell history or process "
            "listings. Prefer --input-json - for stdin input; interactive input is not echoed."
        )
    if "object" in _schema_types(schema) or "array" in _schema_types(schema):
        description += " Pass this value as JSON."
    return description


def _add_operation_arguments(parser: argparse.ArgumentParser, operation: Operation) -> None:
    schema = operation.input_schema
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        return
    required = set(schema.get("required", ()))
    example = " ".join(
        ("vantage", *command_path_for_operation(operation), "--input-json", "-")
    )

    parser.add_argument(
        "--input-json",
        dest="input_json_source",
        default=argparse.SUPPRESS,
        metavar="PATH|-",
        help=(
            "Read the full catalog-named input object from a UTF-8 JSON file or stdin using '-'. "
            f"Example: {example}. Interactive stdin is not echoed. Prefer this for sensitive "
            "values to keep them out of shell history and process arguments; do not combine "
            "with individual input flags."
        ),
    )

    for name, property_schema in properties.items():
        if not isinstance(name, str) or not isinstance(property_schema, Mapping):
            continue
        option = "--" + name.replace("_", "-")
        if option == "--input-json":
            raise ValueError(f"catalog input {operation.name}.{name} conflicts with --input-json")
        if option in _DOWNLOAD_OPTION_NAMES and operation.download:
            raise ValueError(f"catalog input {operation.name}.{name} conflicts with a CLI option")
        destination = f"input__{name}"
        option_help = _schema_option_help(
            name, property_schema, required=name in required
        )
        types = _schema_types(property_schema)
        if types == ("boolean",):
            parser.add_argument(
                option,
                dest=destination,
                nargs="?",
                const=True,
                default=argparse.SUPPRESS,
                metavar="BOOL",
                help=option_help,
            )
            parser.add_argument(
                "--no-" + name.replace("_", "-"),
                dest=destination,
                action="store_const",
                const=False,
                default=argparse.SUPPRESS,
                help=f"Set {name.replace('_', ' ')} to false.",
            )
        else:
            parser.add_argument(
                option,
                dest=destination,
                default=argparse.SUPPRESS,
                metavar=_schema_metavar(property_schema),
                help=option_help,
            )


def _add_common_options(
    parser: argparse.ArgumentParser,
    *,
    root: bool = False,
    include_base_url: bool = True,
    include_format: bool = True,
) -> None:
    default = None if root else argparse.SUPPRESS
    format_default = "text" if root else argparse.SUPPRESS
    if include_base_url:
        parser.add_argument(
            "--base-url",
            default=default,
            metavar="LOOPBACK_URL",
            help=(
                "Vantage backend HTTP URL (must use a loopback host). Place this before the "
                "command when that operation also accepts a provider --base-url."
            ),
        )
    if include_format:
        parser.add_argument(
            "--format",
            default=format_default,
            metavar="text|json",
            help="Output format; streamed JSON is emitted as one JSON object per line.",
        )


def _add_command_node(
    parser: argparse.ArgumentParser, node: _CommandNode, *, include_mcp: bool = False
) -> None:
    subparsers = parser.add_subparsers(
        dest="_command",
        required=True,
        parser_class=_CliArgumentParser,
    )
    if include_mcp:
        if "mcp" in node.children:
            raise ValueError("catalog operation group conflicts with the reserved mcp command")
        mcp_parser = subparsers.add_parser(
            "mcp",
            help="Run Vantage's local MCP server over stdio.",
            description=(
                "Expose the Vantage operation catalog over MCP stdio. The server reuses the "
                "already-running Vantage backend and does not start another API server."
            ),
        )
        mcp_parser.set_defaults(mcp_server=True)
    for name, child in node.children.items():
        if child.operation is not None:
            operation = child.operation
            description = operation.description
            if operation.availability != "available":
                reason = operation.unavailable_reason or "No backend bridge is available."
                description += f"\n\nUnavailable: {reason}"
            command = subparsers.add_parser(
                name,
                help=_operation_help(operation),
                description=description,
                formatter_class=argparse.RawDescriptionHelpFormatter,
            )
            command.set_defaults(operation_name=operation.name)
            property_names = operation.input_schema.get("properties", {})
            if not isinstance(property_names, Mapping):
                property_names = {}
            _add_common_options(
                command,
                include_base_url="base_url" not in property_names,
                include_format="format" not in property_names,
            )
            _add_operation_arguments(command, operation)
            if operation.download:
                command.add_argument(
                    "--output",
                    metavar="PATH",
                    help="Write the downloaded file here; omit to write raw bytes to stdout.",
                )
        else:
            group = subparsers.add_parser(
                name,
                help=_group_help(child),
                description=f"Vantage {name} operations generated from the operation catalog.",
            )
            _add_command_node(group, child)


def build_parser() -> argparse.ArgumentParser:
    """Build catalog command groups and the standalone MCP server entry."""

    parser = _CliArgumentParser(
        prog="vantage",
        description="Run Vantage product operations through the local backend.",
    )
    _add_common_options(parser, root=True)
    _add_command_node(parser, _command_tree(), include_mcp=True)
    return parser


def _parse_cli_value(value: str, schema: Mapping[str, Any], option: str) -> Any:
    types = _schema_types(schema)
    if "null" in types and value == "null":
        return None

    if types == ("boolean",):
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False
        # Leave schema/type validation to VantageClient; never reflect input.
        return value

    if "string" in types and set(types) <= {"string", "null"}:
        return value

    if "object" in types or "array" in types or len(types) > 1:
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            raise _InputError(f"--{option} requires valid JSON.") from None

    if types == ("integer",):
        try:
            return int(value, 10)
        except ValueError:
            return value
    if types == ("number",):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def _operation_arguments(namespace: argparse.Namespace, operation: Operation) -> dict[str, Any]:
    parsed = vars(namespace)
    properties = operation.input_schema.get("properties", {})
    arguments = {}
    if not isinstance(properties, Mapping):
        return arguments

    input_json_source = parsed.get("input_json_source")
    provided_fields = [
        name
        for name in properties
        if f"input__{name}" in parsed
    ]
    if input_json_source is not None:
        if provided_fields:
            raise _InputError(
                "--input-json cannot be combined with individual operation input flags."
            )
        return _read_json_arguments(input_json_source)

    for name, schema in properties.items():
        destination = f"input__{name}"
        if destination not in parsed:
            continue
        value = parsed[destination]
        if isinstance(schema, Mapping) and isinstance(value, str):
            value = _parse_cli_value(value, schema, name.replace("_", "-"))
        arguments[name] = value
    return arguments


def _read_json_arguments(source: str) -> dict[str, Any]:
    if source == "-":
        try:
            stdin = sys.stdin
            if stdin.isatty():
                serialized = getpass.getpass(
                    "Vantage input JSON (not echoed; enter one line): ",
                    stream=sys.stderr,
                )
            else:
                binary_stdin = getattr(stdin, "buffer", None)
                if binary_stdin is not None:
                    serialized = binary_stdin.read().decode("utf-8")
                else:
                    serialized = stdin.read()
        except (EOFError, OSError, UnicodeError, ValueError):
            raise _InputError("Unable to read UTF-8 JSON input from stdin.") from None
    else:
        try:
            serialized = Path(source).read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            raise _InputError("Unable to read the UTF-8 JSON input file.") from None

    try:
        arguments = json.loads(serialized)
    except (json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise _InputError("--input-json must contain a valid JSON object.") from None
    if not isinstance(arguments, dict):
        raise _InputError("--input-json must contain a JSON object.")
    return arguments


def _safe_json(value: Any, *, compact: bool) -> str:
    try:
        if compact:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        raise _OutputError("Unable to render the Vantage response as JSON.") from None


def _write_stdout(value: str) -> None:
    try:
        output = sys.stdout
        encoded = value.encode("utf-8")
        reconfigure = getattr(output, "reconfigure", None)
        encoding = str(getattr(output, "encoding", "")).lower().replace("_", "-")
        if callable(reconfigure):
            if encoding not in {"utf-8", "utf8"}:
                reconfigure(encoding="utf-8", errors="strict")
            output.write(value)
            output.flush()
        else:
            binary_output = getattr(output, "buffer", None)
            if binary_output is None:
                output.write(value)
                output.flush()
            else:
                output.flush()
                binary_output.write(encoded)
                binary_output.flush()
    except (OSError, UnicodeError, ValueError, TypeError):
        raise _OutputError("Unable to write Vantage output to stdout.") from None


def _render_response(result: Any, output_format: str) -> None:
    if output_format == "json":
        _write_stdout(_safe_json(result, compact=False) + "\n")
    elif isinstance(result, str):
        _write_stdout(result + ("" if result.endswith("\n") else "\n"))
    else:
        _write_stdout(_safe_json(result, compact=False) + "\n")


def _render_stream(result: Any, output_format: str) -> None:
    close = getattr(result, "close", None)
    try:
        for item in result:
            if output_format == "json":
                record = _safe_json(item, compact=True)
            elif isinstance(item, str):
                record = item
            else:
                record = _safe_json(item, compact=True)
            _write_stdout(record + ("" if record.endswith("\n") else "\n"))
    except TypeError:
        raise _OutputError("The Vantage operation did not return a readable stream.") from None
    finally:
        if callable(close):
            close()


def _render_download(result: Any, output_path: str | None) -> None:
    if not isinstance(result, FileDownload):
        raise _OutputError("The Vantage operation did not return a downloadable file.")
    try:
        if output_path:
            Path(output_path).write_bytes(result.content)
        else:
            binary_stdout = getattr(sys.stdout, "buffer", None)
            if binary_stdout is None:
                raise OSError("stdout has no binary stream")
            binary_stdout.write(result.content)
            binary_stdout.flush()
    except (OSError, ValueError, TypeError):
        raise _OutputError("Unable to write the downloaded Vantage file.") from None


def _write_error(message: str) -> None:
    try:
        sys.stderr.write(f"Error: {message}\n")
        sys.stderr.flush()
    except (OSError, UnicodeError, ValueError):
        pass


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested catalog operation and return a stable process code."""

    parser = build_parser()
    try:
        namespace = parser.parse_args(argv)
    except _UsageError:
        _write_error("Invalid command-line arguments. Run 'vantage --help' for usage.")
        return EXIT_INPUT_ERROR

    try:
        if getattr(namespace, "mcp_server", False):
            from src.mcp_server import run_stdio

            run_stdio(namespace.base_url)
            return EXIT_OK

        output_format = namespace.format
        if output_format not in {"text", "json"}:
            raise _InputError("--format must be either text or json.")
        operation = get_operation(namespace.operation_name)
        arguments = _operation_arguments(namespace, operation)
        client = VantageClient(namespace.base_url)
        result = client.invoke(operation, arguments)

        if operation.stream:
            _render_stream(result, output_format)
        elif operation.download:
            _render_download(result, getattr(namespace, "output", None))
        else:
            _render_response(result, output_format)
        return EXIT_OK
    except _InputError as error:
        _write_error(str(error))
        return EXIT_INPUT_ERROR
    except OperationUnavailableError as error:
        _write_error(str(error))
        return EXIT_UNAVAILABLE
    except BackendUnavailableError as error:
        _write_error(str(error))
        return EXIT_BACKEND_UNAVAILABLE
    except BackendHTTPError as error:
        _write_error(str(error))
        return EXIT_BACKEND_HTTP_ERROR
    except ArgumentValidationError as error:
        _write_error(str(error))
        return EXIT_INPUT_ERROR
    except VantageClientError as error:
        _write_error(str(error))
        return EXIT_CLIENT_ERROR
    except requests.exceptions.RequestException:
        _write_error(
            "The connection to Vantage backend was interrupted while reading the response."
        )
        return EXIT_BACKEND_UNAVAILABLE
    except ValueError as error:
        # URL normalization and catalog conversion errors are safe; never print
        # user-provided data or a full URL to the terminal.
        message = str(error)
        if "loopback" in message.lower() or "http" in message.lower():
            _write_error(message)
        else:
            _write_error("Invalid Vantage command input.")
        return EXIT_INPUT_ERROR
    except _OutputError as error:
        _write_error(str(error))
        return EXIT_OUTPUT_ERROR
    except OSError:
        _write_error("Unable to write Vantage output.")
        return EXIT_OUTPUT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())

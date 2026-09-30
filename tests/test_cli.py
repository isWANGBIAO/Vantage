import io
import json
from pathlib import Path

import pytest
import requests

from src.services.automation_catalog import OPERATIONS
from src.services.vantage_client import (
    ArgumentValidationError,
    BackendHTTPError,
    BackendUnavailableError,
    FileDownload,
    OperationUnavailableError,
    VantageClient,
)


def _cli_path(operation_name):
    return [segment.replace("_", "-") for segment in operation_name.split(".")]


class _RecordingClient:
    def __init__(self, result=None, *, error=None, base_url=None):
        self.result = result
        self.error = error
        self.base_url = base_url
        self.calls = []

    def invoke(self, operation, arguments):
        self.calls.append((operation.name, arguments))
        if self.error:
            raise self.error
        return self.result


class _FakeSession:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


class _Response:
    status_code = 200
    headers = {"Content-Type": "application/json"}
    text = ""
    content = b""

    def __init__(self, payload=None):
        self.payload = payload
        self.closed = False

    def json(self):
        return self.payload

    def close(self):
        self.closed = True


def test_help_lists_every_catalog_group_including_unavailable_operations(capsys):
    from src import cli

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--help"])

    output = capsys.readouterr().out
    assert exit_info.value.code == 0
    assert "system" in output
    assert "action-plan" in output
    assert "project-progress" in output
    assert "onboarding" in output


def test_help_exposes_the_catalog_mcp_server_entry(capsys):
    from src import cli

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--help"])

    assert exit_info.value.code == 0
    assert "mcp" in capsys.readouterr().out


def test_mcp_entry_dispatches_stdio_server_with_global_backend_url(monkeypatch):
    from src import cli, mcp_server

    calls = []
    monkeypatch.setattr(mcp_server, "run_stdio", lambda base_url=None: calls.append(base_url))

    assert cli.main(["--base-url", "http://127.0.0.1:9555", "mcp"]) == cli.EXIT_OK
    assert calls == ["http://127.0.0.1:9555"]


@pytest.mark.parametrize("operation", OPERATIONS, ids=lambda item: item.name)
def test_every_catalog_operation_has_a_discoverable_help_path(operation, capsys):
    from src import cli

    with pytest.raises(SystemExit) as exit_info:
        cli.main([*_cli_path(operation.name), "--help"])

    output = capsys.readouterr().out
    assert exit_info.value.code == 0
    assert operation.description in output
    assert "--format" in output
    assert "--input-json" in output
    for name, schema in operation.input_schema.get("properties", {}).items():
        option = "--" + name.replace("_", "-")
        assert option in output
        if schema.get("type") == "boolean":
            assert "--no-" + name.replace("_", "-") in output
    if operation.download:
        assert "--output" in output
    if operation.availability != "available":
        assert operation.unavailable_reason in output


def test_cli_parses_schema_derived_nested_arrays_nullable_and_boolean_values(monkeypatch, capsys):
    from src import cli

    client = _RecordingClient(result={"ok": True})
    monkeypatch.setattr(cli, "VantageClient", lambda base_url=None: client)
    provider_payload = {
        "providers": {
            "local": {
                "route": "local",
                "enabled": True,
                "models": ["DeepSeek-V4-Flash-0731", "small-model"],
                "last_refreshed_at": None,
            }
        }
    }

    result = cli.main(
        [
            "settings",
            "update",
            "--provider-config",
            json.dumps(provider_payload),
            "--voice-models",
            '["voice-a", "voice-b"]',
            "--voice-last-refreshed-at",
            "2026-09-29T12:00:00Z",
            "--image-last-refreshed-at",
            "null",
            "--launch-at-login",
            "false",
            "--format",
            "json",
        ]
    )

    output = capsys.readouterr()
    assert result == 0
    assert client.calls == [
        (
            "settings.update",
            {
                "provider_config": provider_payload,
                "voice_models": ["voice-a", "voice-b"],
                "voice_last_refreshed_at": "2026-09-29T12:00:00Z",
                "image_last_refreshed_at": None,
                "launch_at_login": False,
            },
        )
    ]
    assert json.loads(output.out) == {"ok": True}
    assert output.err == ""


def test_cli_accepts_global_options_before_command_and_boolean_shorthand(monkeypatch, capsys):
    from src import cli

    client = _RecordingClient(result={"accepted": True})

    def make_client(base_url=None):
        client.base_url = base_url
        return client

    monkeypatch.setattr(cli, "VantageClient", make_client)

    result = cli.main(
        [
            "--format",
            "json",
            "--base-url",
            "http://127.0.0.1:8123",
            "action-plan",
            "jobs",
            "create",
            "--replace-today",
        ]
    )

    output = capsys.readouterr()
    assert result == 0
    assert client.base_url == "http://127.0.0.1:8123"
    assert client.calls == [("action_plan.jobs.create", {"replace_today": True})]
    assert json.loads(output.out) == {"accepted": True}
    assert output.err == ""


def test_provider_base_url_and_global_backend_base_url_remain_distinct(
    monkeypatch, capsys
):
    from src import cli

    client = _RecordingClient(result={"models": []})

    def make_client(base_url=None):
        client.base_url = base_url
        return client

    monkeypatch.setattr(cli, "VantageClient", make_client)

    result = cli.main(
        [
            "--base-url",
            "http://127.0.0.1:8123",
            "models",
            "discover",
            "--base-url",
            "https://provider.example/v1",
            "--format",
            "json",
        ]
    )

    output = capsys.readouterr()
    assert result == 0
    assert client.base_url == "http://127.0.0.1:8123"
    assert client.calls == [
        ("models.discover", {"base_url": "https://provider.example/v1"})
    ]
    assert json.loads(output.out) == {"models": []}
    assert output.err == ""


def test_cli_keeps_vantage_client_schema_validation_authoritative(monkeypatch, capsys):
    from src import cli

    session = _FakeSession(_Response({"unexpected": True}))
    monkeypatch.setattr(
        cli,
        "VantageClient",
        lambda base_url=None: VantageClient(base_url, session=session),
    )

    result = cli.main(
        ["system", "media", "open-folder", "--type", "SECRET-CANARY"]
    )

    output = capsys.readouterr()
    assert result == cli.EXIT_INPUT_ERROR
    assert session.calls == []
    assert "one of the allowed values" in output.err
    assert "SECRET-CANARY" not in output.err
    assert output.out == ""


def test_cli_forwards_json_response_in_text_format(capsys, monkeypatch):
    from src import cli

    client = _RecordingClient(result={"status": "ready", "count": 2})
    monkeypatch.setattr(cli, "VantageClient", lambda base_url=None: client)

    result = cli.main(["system", "status", "read"])

    output = capsys.readouterr()
    assert result == 0
    assert json.loads(output.out) == {"status": "ready", "count": 2}
    assert output.err == ""


def test_cli_writes_json_as_utf8_even_when_stdout_encoding_is_ascii(monkeypatch):
    from src import cli

    stdout = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    stdout_bytes = stdout.buffer
    stderr = io.StringIO()
    result_payload = {"message": "中文与🙂"}
    client = _RecordingClient(result=result_payload)
    monkeypatch.setattr(cli, "VantageClient", lambda base_url=None: client)
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(cli.sys, "stderr", stderr)

    result = cli.main(["system", "status", "read", "--format", "json"])

    assert result == 0
    assert stdout.encoding.lower() == "utf-8"
    assert stdout_bytes.getvalue().decode("utf-8").splitlines() == (
        json.dumps(result_payload, ensure_ascii=False, indent=2) + "\n"
    ).splitlines()
    assert stderr.getvalue() == ""


def test_cli_writes_stream_records_as_utf8_even_when_stdout_encoding_is_gbk(
    monkeypatch,
):
    from src import cli

    stdout = io.TextIOWrapper(io.BytesIO(), encoding="gbk")
    stdout_bytes = stdout.buffer
    stderr = io.StringIO()
    client = _RecordingClient(result=iter([{"content": "体感温度🌡️"}]))
    monkeypatch.setattr(cli, "VantageClient", lambda base_url=None: client)
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(cli.sys, "stderr", stderr)

    result = cli.main(["chat", "send", "--message", "test", "--format", "json"])

    assert result == 0
    assert stdout.encoding.lower() == "utf-8"
    assert stdout_bytes.getvalue().decode("utf-8").splitlines() == [
        '{"content":"体感温度🌡️"}'
    ]
    assert stderr.getvalue() == ""


def test_cli_reads_full_sensitive_json_from_stdin_without_echo(monkeypatch, capsys):
    from src import cli

    secret = "CLI-SECRET-CANARY"
    arguments = {
        "voice_api_key": secret,
        "provider_config": {
            "providers": {
                "local": {
                    "route": "local",
                    "api_key": "NESTED-SECRET-CANARY",
                    "models": ["model-a"],
                }
            }
        },
        "launch_at_login": False,
    }
    client = _RecordingClient(result={"saved": True})
    monkeypatch.setattr(cli, "VantageClient", lambda base_url=None: client)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(json.dumps(arguments)))

    result = cli.main(["settings", "update", "--input-json", "-", "--format", "json"])

    output = capsys.readouterr()
    assert result == 0
    assert client.calls == [("settings.update", arguments)]
    assert json.loads(output.out) == {"saved": True}
    assert secret not in output.out + output.err
    assert "NESTED-SECRET-CANARY" not in output.out + output.err


def test_cli_reads_full_json_arguments_from_utf8_file(tmp_path, monkeypatch, capsys):
    from src import cli

    arguments = {"voice_model": "中文模型", "launch_at_login": False}
    input_file = tmp_path / "settings.json"
    input_file.write_text(json.dumps(arguments, ensure_ascii=False), encoding="utf-8")
    client = _RecordingClient(result={"saved": True})
    monkeypatch.setattr(cli, "VantageClient", lambda base_url=None: client)

    result = cli.main(
        ["settings", "update", "--input-json", str(input_file), "--format", "json"]
    )

    output = capsys.readouterr()
    assert result == 0
    assert client.calls == [("settings.update", arguments)]
    assert json.loads(output.out) == {"saved": True}
    assert output.err == ""


def test_cli_reads_interactive_json_through_a_non_echo_prompt(monkeypatch, capsys):
    from src import cli

    secret = "TTY-SECRET-CANARY"
    arguments = {"voice_api_key": secret}
    prompt_inputs = []

    class TTYStdin(io.StringIO):
        def isatty(self):
            return True

    def read_without_echo(prompt, *, stream):
        prompt_inputs.append((prompt, stream))
        return json.dumps(arguments)

    client = _RecordingClient(result={"saved": True})
    monkeypatch.setattr(cli, "VantageClient", lambda base_url=None: client)
    monkeypatch.setattr(cli.sys, "stdin", TTYStdin())
    monkeypatch.setattr("getpass.getpass", read_without_echo)

    result = cli.main(["settings", "update", "--input-json", "-"])

    output = capsys.readouterr()
    assert result == 0
    assert client.calls == [("settings.update", arguments)]
    assert len(prompt_inputs) == 1
    assert "not echoed" in prompt_inputs[0][0].lower()
    assert prompt_inputs[0][1] is cli.sys.stderr
    assert secret not in output.out + output.err


def test_cli_rejects_input_json_combined_with_field_flags_without_echo(
    monkeypatch, capsys
):
    from src import cli

    secret = "ARGV-SECRET-CANARY"
    stdin = io.StringIO('{"voice_api_key":"JSON-SECRET-CANARY"}')
    client = _RecordingClient(result={"saved": True})
    monkeypatch.setattr(cli, "VantageClient", lambda base_url=None: client)
    monkeypatch.setattr(cli.sys, "stdin", stdin)

    result = cli.main(
        [
            "settings",
            "update",
            "--input-json",
            "-",
            "--voice-api-key",
            secret,
        ]
    )

    output = capsys.readouterr()
    assert result == cli.EXIT_INPUT_ERROR
    assert "cannot be combined" in output.err
    assert secret not in output.out + output.err
    assert "JSON-SECRET-CANARY" not in output.out + output.err
    assert stdin.tell() == 0
    assert client.calls == []


def test_cli_validates_json_input_through_vantage_client(monkeypatch, capsys):
    from src import cli

    secret = "INVALID-ENUM-CANARY"
    session = _FakeSession(_Response({"unexpected": True}))
    monkeypatch.setattr(
        cli,
        "VantageClient",
        lambda base_url=None: VantageClient(base_url, session=session),
    )
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(json.dumps({"type": secret})))

    result = cli.main(["system", "media", "open-folder", "--input-json", "-"])

    output = capsys.readouterr()
    assert result == cli.EXIT_INPUT_ERROR
    assert session.calls == []
    assert "allowed values" in output.err
    assert secret not in output.out + output.err


def test_cli_help_recommends_input_json_for_sensitive_values(capsys):
    from src import cli

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["settings", "update", "--help"])

    output = capsys.readouterr().out
    assert exit_info.value.code == 0
    assert "--input-json" in output
    assert "shell history" in output
    assert "--voice-api-key" in output
    assert "vantage settings update --input-json -" in " ".join(output.split())


def test_cli_warns_when_nested_write_only_fields_are_encoded_in_json_flags(capsys):
    from src import cli

    with pytest.raises(SystemExit):
        cli.main(["settings", "update", "--help"])

    lines = capsys.readouterr().out.splitlines()

    def option_help(option):
        option_name = option.split(maxsplit=1)[0]
        start = next(
            index
            for index, line in enumerate(lines)
            if line.lstrip().startswith(option_name + " ")
        )
        end = next(
            (
                index
                for index in range(start + 1, len(lines))
                if lines[index].startswith("  --")
            ),
            len(lines),
        )
        return " ".join(lines[start:end])

    description = option_help("--provider-config JSON_OBJECT")
    assert "shell history" in description
    assert "--input-json -" in description
    assert not any(line.lstrip().startswith("--provider ") for line in lines)


def test_cli_writes_each_stream_record_immediately_as_ndjson(monkeypatch):
    from src import cli

    events = []
    observations = []

    def stream():
        events.append({"type": "delta", "content": "甲"})
        yield events[-1]
        observations.append(len(sys_stdout.records))
        events.append({"type": "done", "content": "乙"})
        yield events[-1]

    class TrackingStdout(io.StringIO):
        def __init__(self):
            super().__init__()
            self.records = []

        def write(self, value):
            self.records.append(value)
            return super().write(value)

    import sys

    sys_stdout = TrackingStdout()
    client = _RecordingClient(result=stream())
    monkeypatch.setattr(cli, "VantageClient", lambda base_url=None: client)
    monkeypatch.setattr(cli.sys, "stdout", sys_stdout)
    monkeypatch.setattr(cli.sys, "stderr", io.StringIO())

    result = cli.main(["chat", "send", "--message", "你好", "--format", "json"])

    assert result == 0
    assert observations == [1]
    assert sys_stdout.getvalue().splitlines() == [
        '{"type":"delta","content":"甲"}',
        '{"type":"done","content":"乙"}',
    ]


def test_cli_emits_stream_text_records_in_order(monkeypatch, capsys):
    from src import cli

    client = _RecordingClient(result=iter(["第一段", "第二段"]))
    monkeypatch.setattr(cli, "VantageClient", lambda base_url=None: client)

    result = cli.main(["chat", "send", "--message", "你好", "--format", "text"])

    output = capsys.readouterr()
    assert result == 0
    assert output.out.splitlines() == ["第一段", "第二段"]
    assert output.err == ""


def test_cli_maps_stream_connection_interrupt_to_backend_unavailable_without_echo(
    monkeypatch, capsys
):
    from src import cli

    secret = "SECRET-CANARY"

    def broken_stream():
        raise requests.ConnectionError(f"connection dropped with {secret}")
        yield None

    client = _RecordingClient(result=broken_stream())
    monkeypatch.setattr(cli, "VantageClient", lambda base_url=None: client)

    result = cli.main(["chat", "send", "--message", "hello"])

    output = capsys.readouterr()
    assert result == cli.EXIT_BACKEND_UNAVAILABLE
    assert "interrupted" in output.err
    assert secret not in output.err
    assert output.out == ""


def test_cli_writes_download_bytes_to_requested_output_path(tmp_path, monkeypatch, capsys):
    from src import cli

    target = tmp_path / "export.xlsx"
    client = _RecordingClient(
        result=FileDownload("vantage.xlsx", b"workbook-bytes", "application/xlsx")
    )
    monkeypatch.setattr(cli, "VantageClient", lambda base_url=None: client)

    result = cli.main(["face", "export", "--output", str(target)])

    output = capsys.readouterr()
    assert result == 0
    assert target.read_bytes() == b"workbook-bytes"
    assert output.out == ""
    assert output.err == ""


def test_cli_writes_download_bytes_to_raw_stdout_when_output_is_omitted(monkeypatch):
    from src import cli

    class BinaryStdout:
        def __init__(self):
            self.buffer = io.BytesIO()

    stdout = BinaryStdout()
    client = _RecordingClient(result=FileDownload("vantage.xlsx", b"raw\x00bytes"))
    monkeypatch.setattr(cli, "VantageClient", lambda base_url=None: client)
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(cli.sys, "stderr", io.StringIO())

    result = cli.main(["face", "export"])

    assert result == 0
    assert stdout.buffer.getvalue() == b"raw\x00bytes"


@pytest.mark.parametrize(
    ("error", "expected_exit", "expected_text"),
    [
        (ArgumentValidationError("arguments.type must be one of the allowed values."), 2, "allowed values"),
        (OperationUnavailableError("settings.open_path is unavailable: needs desktop."), 5, "needs desktop"),
        (BackendUnavailableError("Vantage backend is unavailable. Start Vantage and try again."), 3, "Start Vantage"),
        (BackendHTTPError(503), 4, "HTTP 503"),
    ],
)
def test_cli_maps_client_failures_to_stable_exit_codes(
    error, expected_exit, expected_text, monkeypatch, capsys
):
    from src import cli

    client = _RecordingClient(error=error)
    monkeypatch.setattr(cli, "VantageClient", lambda base_url=None: client)

    result = cli.main(["system", "status", "read"])

    output = capsys.readouterr()
    assert result == expected_exit
    assert expected_text in output.err
    assert output.out == ""


def test_cli_does_not_echo_a_secret_on_invalid_json_input(monkeypatch, capsys):
    from src import cli

    secret = "sk-live-SECRET-CANARY"
    client = _RecordingClient()
    monkeypatch.setattr(cli, "VantageClient", lambda base_url=None: client)

    result = cli.main(["settings", "update", "--provider-config", secret])

    output = capsys.readouterr()
    assert result == cli.EXIT_INPUT_ERROR
    assert "JSON" in output.err
    assert secret not in output.err
    assert client.calls == []


def test_cli_rejects_non_loopback_base_url_without_connecting(monkeypatch, capsys):
    from src import cli

    session = _FakeSession(_Response({}))
    monkeypatch.setattr(
        cli,
        "VantageClient",
        lambda base_url=None: VantageClient(base_url, session=session),
    )

    result = cli.main(
        ["system", "status", "read", "--base-url", "https://example.com"]
    )

    output = capsys.readouterr()
    assert result == cli.EXIT_INPUT_ERROR
    assert session.calls == []
    assert "loopback" in output.err
    assert "https://example.com" not in output.err


def test_cli_reports_file_output_errors_with_stable_exit_code(
    monkeypatch, capsys, tmp_path
):
    from src import cli

    client = _RecordingClient(result=FileDownload("vantage.xlsx", b"data"))
    monkeypatch.setattr(cli, "VantageClient", lambda base_url=None: client)

    result = cli.main(
        ["face", "export", "--output", str(tmp_path / "missing" / "export.xlsx")]
    )

    output = capsys.readouterr()
    assert result == cli.EXIT_OUTPUT_ERROR
    assert "write" in output.err.lower()
    assert output.out == ""


def test_cli_displays_catalog_unavailable_operation_without_backend_request(
    monkeypatch, capsys
):
    from src import cli

    client = _RecordingClient(
        error=OperationUnavailableError(
            "settings.open_path is unavailable: This action requires the running Electron desktop UI."
        )
    )
    monkeypatch.setattr(cli, "VantageClient", lambda base_url=None: client)

    result = cli.main(["settings", "open-path", "--path-key", "history"])

    output = capsys.readouterr()
    assert result == cli.EXIT_UNAVAILABLE
    assert "running Electron desktop UI" in output.err
    assert client.calls == [("settings.open_path", {"path_key": "history"})]
    assert output.out == ""


def test_catalog_cli_paths_are_unique_and_cover_every_operation():
    paths = [_cli_path(operation.name) for operation in OPERATIONS]

    assert len(paths) == len({tuple(path) for path in paths})
    assert {_cli_path(operation.name)[-1] for operation in OPERATIONS}

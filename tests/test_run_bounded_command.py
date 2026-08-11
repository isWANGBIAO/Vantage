from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

import pytest


def _module():
    from src.scripts import run_bounded_command

    return run_bounded_command


def test_command_bridge_terminates_early_parent_descendant_tree(tmp_path):
    module = _module()
    sentinel = tmp_path / "descendant-survived.txt"
    child_source = (
        "import pathlib,time; "
        "time.sleep(1); "
        f"pathlib.Path({str(sentinel)!r}).write_text('survived')"
    )
    parent_source = (
        "import subprocess,sys; "
        "subprocess.Popen([sys.executable, '-c', "
        f"{child_source!r}], stdout=sys.stdout, stderr=sys.stderr)"
    )

    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        module.run_bounded_command(
            [sys.executable, "-c", parent_source],
            timeout_seconds=0.2,
            output_limit_bytes=1024,
        )
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
    time.sleep(1.1)
    assert not sentinel.exists()


def test_cli_redacts_credentials_and_known_paths_on_failure(tmp_path, capsys):
    module = _module()
    payload = (
        f"NPM_TOKEN=secret ghp_example token=value {tmp_path} "
        "password=hunter2 client_secret=hidden"
    )
    source = f"import sys; sys.stderr.write({payload!r}); raise SystemExit(7)"

    result = module.main(
        [
            "--timeout-seconds",
            "2",
            "--output-limit-bytes",
            "1024",
            "--redact-path",
            "<PROJECT_ROOT>",
            str(tmp_path),
            "--",
            sys.executable,
            "-c",
            source,
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "NPM_TOKEN=secret" not in captured.err
    assert "ghp_example" not in captured.err
    assert "token=value" not in captured.err
    assert "hunter2" not in captured.err
    assert "client_secret=hidden" not in captured.err
    assert str(tmp_path) not in captured.err
    assert "<PROJECT_ROOT>" in captured.err


def test_cli_success_output_is_bounded_and_redacted(tmp_path, capsys):
    module = _module()
    source = (
        "print('A' * 4096); "
        f"print({json.dumps('NPM_TOKEN=secret ' + str(tmp_path))})"
    )

    result = module.main(
        [
            "--timeout-seconds",
            "2",
            "--output-limit-bytes",
            "512",
            "--redact-path",
            "<PROJECT_ROOT>",
            str(tmp_path),
            "--",
            sys.executable,
            "-c",
            source,
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert len(captured.out.encode("utf-8")) <= 512
    assert "output truncated" in captured.out
    assert "NPM_TOKEN=secret" not in captured.out
    assert str(tmp_path) not in captured.out


def test_script_runs_from_a_non_repository_working_directory(tmp_path):
    script_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "scripts"
        / "run_bounded_command.py"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--timeout-seconds",
            "2",
            "--output-limit-bytes",
            "1024",
            "--",
            sys.executable,
            "-c",
            "print('bridge-ready')",
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "bridge-ready\n"

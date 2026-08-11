from pathlib import Path
import sys
import time

from src.scripts.run_packaging_builds import _run_command, resolve_build_worker_count


def test_resolve_build_worker_count_uses_available_commands_not_more_processes():
    assert resolve_build_worker_count(None, command_count=2, cpu_count=32) == 2
    assert resolve_build_worker_count(32, command_count=2, cpu_count=32) == 2
    assert resolve_build_worker_count(1, command_count=2, cpu_count=32) == 1


def test_resolve_build_worker_count_handles_invalid_or_empty_inputs():
    assert resolve_build_worker_count(0, command_count=2, cpu_count=32) == 2
    assert resolve_build_worker_count(-5, command_count=2, cpu_count=32) == 2
    assert resolve_build_worker_count(None, command_count=0, cpu_count=32) == 1
    resolved_from_current_machine = resolve_build_worker_count(None, command_count=2, cpu_count=None)
    assert 1 <= resolved_from_current_machine <= 2


def test_packaging_child_output_is_redacted_and_bounded(tmp_path, capsys):
    secret = "sk-1234567890abcdef"
    source = (
        "import sys; "
        f"path={str(tmp_path)!r}; secret={secret!r}; "
        "sys.stdout.write((f'path={path} api_key={secret}\\n') * 10000)"
    )

    returncode = _run_command(
        "probe",
        [sys.executable, "-c", source],
        Path(tmp_path),
        timeout_seconds=5,
        output_limit_bytes=2048,
    )
    output = capsys.readouterr().out

    assert returncode == 0
    assert str(tmp_path) not in output
    assert secret not in output
    assert "<PROJECT_ROOT>" in output
    assert "[REDACTED]" in output
    assert "output truncated" in output
    assert len(output.encode("utf-8")) < 4096


def test_packaging_child_timeout_returns_failure_promptly(tmp_path):
    started = time.monotonic()

    returncode = _run_command(
        "probe",
        [sys.executable, "-c", "import time; time.sleep(10)"],
        Path(tmp_path),
        timeout_seconds=0.2,
    )

    assert returncode != 0
    assert time.monotonic() - started < 3

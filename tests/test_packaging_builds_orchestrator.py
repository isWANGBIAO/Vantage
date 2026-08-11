from pathlib import Path
import os
import sys
import time

import psutil

from src.scripts import run_packaging_builds as packaging_module
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
    secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    source = (
        "import sys; "
        f"path={str(tmp_path)!r}; secret={secret!r}; "
        "sys.stdout.write((f'path={path} token={secret} ') * 100000)"
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
    assert "<WORKER_CWD>" in output
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


def test_packaging_timeout_terminates_pipe_inheriting_descendant(tmp_path, capsys):
    descendant_pid_path = tmp_path / "descendant.pid"
    descendant = "import time; print('descendant-ready', flush=True); time.sleep(5)"
    parent = (
        "import pathlib, subprocess, sys, time; "
        f"child=subprocess.Popen([sys.executable, '-c', {descendant!r}]); "
        f"pathlib.Path({str(descendant_pid_path)!r}).write_text(str(child.pid), encoding='utf-8'); "
        "print('parent-ready', flush=True); time.sleep(5)"
    )
    started = time.monotonic()

    returncode = _run_command(
        "probe",
        [sys.executable, "-c", parent],
        Path(tmp_path),
        timeout_seconds=0.5,
        output_limit_bytes=1024,
    )

    elapsed = time.monotonic() - started
    assert returncode == 124
    assert elapsed < 2.5
    assert descendant_pid_path.exists()
    descendant_pid = int(descendant_pid_path.read_text(encoding="utf-8"))
    try:
        descendant_process = psutil.Process(descendant_pid)
    except psutil.NoSuchProcess:
        descendant_process = None
    if descendant_process is not None:
        try:
            descendant_process.wait(timeout=3)
        except psutil.NoSuchProcess:
            pass
        assert (
            not descendant_process.is_running()
            or descendant_process.status() == psutil.STATUS_ZOMBIE
        )
    output = capsys.readouterr().out
    assert "parent-ready" in output
    assert "descendant-ready" in output
    assert len(output.encode("utf-8")) < 2048


def test_frontend_worker_redacts_project_paths_outside_its_cwd(capsys):
    worker_cwd = packaging_module.PROJECT_ROOT / "src" / "webapp"
    project_path = packaging_module.PROJECT_ROOT / "src" / "server.py"

    returncode = _run_command(
        "frontend",
        [sys.executable, "-c", f"print({str(project_path)!r})"],
        worker_cwd,
        timeout_seconds=5,
    )

    output = capsys.readouterr().out
    assert returncode == 0
    assert str(packaging_module.PROJECT_ROOT) not in output
    assert f"<PROJECT_ROOT>{os.sep}src{os.sep}server.py" in output

from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys


def _lock_module():
    return importlib.import_module("src.core.backend_runtime_lock")


def _subprocess_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path.cwd())
    return environment


def _spawn_holder(project_root: Path, body: str) -> subprocess.Popen[str]:
    source = f"""
import os
from pathlib import Path
import sys
import time
from src.core.backend_runtime_lock import backend_runtime_lock

project_root = Path(sys.argv[1])
with backend_runtime_lock(project_root, timeout_seconds=2):
    print("locked", flush=True)
    {body}
"""
    process = subprocess.Popen(
        [sys.executable, "-c", source, str(project_root)],
        env=_subprocess_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    ready = process.stdout.readline().strip()
    assert ready == "locked", process.stderr.read() if process.stderr else ""
    return process


def test_second_process_times_out_without_running_protected_operation(tmp_path):
    holder = _spawn_holder(tmp_path, "time.sleep(10)")
    probe_path = tmp_path / "contender-probe.txt"
    contender_source = """
from pathlib import Path
import sys
from src.core.backend_runtime_lock import backend_runtime_lock

try:
    with backend_runtime_lock(Path(sys.argv[1]), timeout_seconds=0.2):
        Path(sys.argv[2]).write_text("mutated", encoding="utf-8")
except TimeoutError:
    raise SystemExit(23)
raise SystemExit(0)
"""
    try:
        contender = subprocess.run(
            [sys.executable, "-c", contender_source, str(tmp_path), str(probe_path)],
            env=_subprocess_environment(),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    finally:
        holder.terminate()
        holder.wait(timeout=5)

    assert contender.returncode == 23, contender.stderr
    assert not probe_path.exists()


def test_holder_crash_releases_lock_even_when_lock_file_remains(tmp_path):
    holder = _spawn_holder(tmp_path, "os._exit(17)")
    assert holder.wait(timeout=5) == 17

    lock_module = _lock_module()
    lock_path = lock_module.backend_runtime_lock_path(tmp_path)
    assert lock_path.exists()
    with lock_module.backend_runtime_lock(tmp_path, timeout_seconds=1):
        (tmp_path / "after-crash.txt").write_text("acquired", encoding="utf-8")

    assert (tmp_path / "after-crash.txt").read_text(encoding="utf-8") == "acquired"


def test_residual_unlocked_file_does_not_block_lock_acquisition(tmp_path):
    lock_module = _lock_module()
    lock_path = lock_module.backend_runtime_lock_path(tmp_path)
    lock_path.write_bytes(b"stale")

    with lock_module.backend_runtime_lock(tmp_path, timeout_seconds=1):
        assert lock_module.backend_runtime_lock_is_held(tmp_path)


def test_lock_supervisor_sets_inherited_marker_and_returns_child_status(tmp_path):
    lock_module = _lock_module()
    output_path = tmp_path / "inherited-lock.txt"
    child_source = (
        "import os, pathlib, sys; "
        "from src.core.backend_runtime_lock import backend_runtime_lock; "
        "root = pathlib.Path(sys.argv[1]); "
        "output = pathlib.Path(sys.argv[2]); "
        "lock = backend_runtime_lock(root, timeout_seconds=0.1); "
        "lock.__enter__(); "
        "output.write_text(os.environ.get("
        "'VANTAGE_BACKEND_RUNTIME_LOCK_HELD', ''), encoding='utf-8'); "
        "lock.__exit__(None, None, None); "
        "raise SystemExit(7)"
    )
    result = subprocess.run(
        [
            sys.executable,
            "src/scripts/run_with_backend_runtime_lock.py",
            "--project-root",
            str(tmp_path),
            "--",
            sys.executable,
            "-c",
            child_source,
            str(tmp_path),
            str(output_path),
        ],
        env=_subprocess_environment(),
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 7, result.stderr
    assert output_path.read_text(encoding="utf-8") == str(
        lock_module.backend_runtime_lock_path(tmp_path)
    )


def test_lock_and_retained_quarantine_artifacts_are_gitignored():
    gitignore = Path(".gitignore").read_text(encoding="utf-8")

    assert ".vantage-backend-runtime.lock" in gitignore
    assert ".venv-backend-runtime-gpu.quarantine-*/" in gitignore

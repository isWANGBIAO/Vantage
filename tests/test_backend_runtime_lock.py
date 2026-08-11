from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest


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


def test_lock_supervisor_child_owns_a_real_shared_lock_and_returns_status(tmp_path):
    lock_module = _lock_module()
    output_path = tmp_path / "inherited-lock.txt"
    child_source = """
import os
import pathlib
import sys
from src.core.backend_runtime_lock import backend_runtime_lock

root = pathlib.Path(sys.argv[1])
output = pathlib.Path(sys.argv[2])
with backend_runtime_lock(root, mode="shared", timeout_seconds=1):
    output.write_text(
        os.environ.get("VANTAGE_BACKEND_RUNTIME_LOCK_HELD", "absent"),
        encoding="utf-8",
    )
raise SystemExit(7)
"""
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
    assert output_path.read_text(encoding="utf-8") == "absent"


def test_forged_inherited_marker_never_bypasses_an_owned_lock(tmp_path):
    lock_module = _lock_module()
    environment = _subprocess_environment()
    environment["VANTAGE_BACKEND_RUNTIME_LOCK_HELD"] = str(
        lock_module.backend_runtime_lock_path(tmp_path)
    )
    holder = _spawn_holder(tmp_path, "time.sleep(10)")
    contender_source = """
from pathlib import Path
import sys
from src.core.backend_runtime_lock import backend_runtime_lock

with backend_runtime_lock(Path(sys.argv[1]), timeout_seconds=0.2):
    raise SystemExit(0)
"""
    try:
        contender = subprocess.run(
            [sys.executable, "-c", contender_source, str(tmp_path)],
            env=environment,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    finally:
        holder.terminate()
        holder.wait(timeout=5)

    assert contender.returncode != 0
    assert "timed out waiting for backend runtime lock" in contender.stderr


def test_supervisor_death_does_not_release_live_child_runtime_lease(tmp_path):
    lock_module = _lock_module()
    ready_path = tmp_path / "child-ready.txt"
    stop_path = tmp_path / "child-stop.txt"
    done_path = tmp_path / "child-done.txt"
    child_source = """
import os
import pathlib
import sys
import time
from src.core.backend_runtime_lock import backend_runtime_lock

root = pathlib.Path(sys.argv[1])
ready = pathlib.Path(sys.argv[2])
stop = pathlib.Path(sys.argv[3])
done = pathlib.Path(sys.argv[4])
with backend_runtime_lock(root, mode="shared", timeout_seconds=2):
    ready.write_text(str(os.getpid()), encoding="utf-8")
    while not stop.exists():
        time.sleep(0.02)
done.write_text("done", encoding="utf-8")
"""
    supervisor = subprocess.Popen(
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
            str(ready_path),
            str(stop_path),
            str(done_path),
        ],
        env=_subprocess_environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while not ready_path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ready_path.exists(), supervisor.stderr.read() if supervisor.stderr else ""
    child_pid = int(ready_path.read_text(encoding="utf-8"))

    try:
        supervisor.kill()
        supervisor.wait(timeout=5)
        with pytest.raises(TimeoutError, match="backend runtime lock"):
            with lock_module.backend_runtime_lock(tmp_path, timeout_seconds=0.2):
                pytest.fail("sync-style exclusive lock entered while child was alive")
    finally:
        stop_path.write_text("stop", encoding="utf-8")
        deadline = time.monotonic() + 5
        while not done_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not done_path.exists():
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(child_pid), "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                os.kill(child_pid, 15)
            pytest.fail("child did not release its runtime lease after stop")

    with lock_module.backend_runtime_lock(tmp_path, timeout_seconds=2):
        assert lock_module.backend_runtime_lock_is_held(tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock semantics")
def test_closing_second_in_process_shared_fd_keeps_external_writer_blocked(tmp_path):
    lock_module = _lock_module()
    primary = lock_module.BackendRuntimeFileLock(
        lock_module.backend_runtime_lock_path(tmp_path),
        mode="shared",
        timeout_seconds=1,
    )
    transient_acquired = threading.Event()
    release_transient = threading.Event()

    def hold_transient_fd() -> None:
        with lock_module.BackendRuntimeFileLock(
            lock_module.backend_runtime_lock_path(tmp_path),
            mode="shared",
            timeout_seconds=1,
        ):
            transient_acquired.set()
            assert release_transient.wait(timeout=2)

    primary.acquire()
    thread = threading.Thread(target=hold_transient_fd)
    thread.start()
    assert transient_acquired.wait(timeout=2)
    release_transient.set()
    thread.join(timeout=2)
    assert not thread.is_alive()

    contender_source = """
from pathlib import Path
import sys
from src.core.backend_runtime_lock import backend_runtime_lock

try:
    with backend_runtime_lock(Path(sys.argv[1]), timeout_seconds=0.2):
        raise SystemExit(0)
except TimeoutError:
    raise SystemExit(23)
"""
    try:
        contender = subprocess.run(
            [sys.executable, "-c", contender_source, str(tmp_path)],
            env=_subprocess_environment(),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    finally:
        primary.release()

    assert contender.returncode == 23, contender.stderr


def test_lock_and_retained_quarantine_artifacts_are_gitignored():
    gitignore = Path(".gitignore").read_text(encoding="utf-8")

    assert ".vantage-backend-runtime.lock" in gitignore
    assert ".venv-backend-runtime-gpu.quarantine-*/" in gitignore

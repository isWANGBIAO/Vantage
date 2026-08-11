from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import psutil
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


@pytest.mark.parametrize(
    ("ready_option", "continue_option"),
    [
        ("--internal-ready-fd", "--internal-continue-fd"),
        ("--internal-ready-handle", "--internal-continue-handle"),
    ],
)
def test_lease_owner_command_keeps_platform_transport_outside_target_command(
    tmp_path, ready_option, continue_option
):
    from src.scripts.run_with_backend_runtime_lock import (
        build_backend_runtime_lease_owner_command,
    )

    target_command = [str(tmp_path / "target-python"), "server.py", "--flag"]
    lock_runner = tmp_path / "lock-runner.py"
    bootstrap_python = tmp_path / "bootstrap-python"
    result = build_backend_runtime_lease_owner_command(
        project_root=tmp_path,
        timeout_seconds=12.5,
        ready_option=ready_option,
        ready_value=17,
        continue_option=continue_option,
        continue_value=19,
        command=target_command,
        bootstrap_python=bootstrap_python,
        lock_runner=lock_runner,
    )

    delimiter_index = result.index("--")
    assert result[0] == str(bootstrap_python)
    assert result[1] == str(lock_runner.resolve())
    assert "--internal-lease-owner" in result[:delimiter_index]
    assert result[result.index(ready_option) + 1] == "17"
    assert result[result.index(continue_option) + 1] == "19"
    assert result[delimiter_index + 1 :] == target_command


def test_lease_owner_ready_wait_times_out_and_stops_an_unready_owner():
    from src.scripts.run_with_backend_runtime_lock import (
        _wait_for_lease_owner_ready,
    )

    read_descriptor, write_descriptor = os.pipe()

    class UnreadyOwner:
        def __init__(self):
            self.killed = False

        def poll(self):
            return -9 if self.killed else None

        def kill(self):
            self.killed = True
            os.close(write_descriptor)

        def wait(self, timeout):
            assert timeout > 0
            return -9

    owner = UnreadyOwner()
    try:
        with pytest.raises(TimeoutError, match="lease owner readiness"):
            _wait_for_lease_owner_ready(
                owner,
                read_descriptor,
                timeout_seconds=0.01,
            )
    finally:
        os.close(read_descriptor)
        if not owner.killed:
            os.close(write_descriptor)

    assert owner.killed


def test_lease_owner_wait_error_stops_target_before_releasing_lease():
    from src.scripts.run_with_backend_runtime_lock import _wait_for_guarded_target

    class TargetWithFailingWait:
        def __init__(self):
            self.alive = True
            self.wait_calls = 0

        def poll(self):
            return None if self.alive else -9

        def wait(self, timeout=None):
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise OSError("simulated wait failure")
            assert timeout is not None and timeout > 0
            return -9

    target = TargetWithFailingWait()
    terminated = []

    def terminate_tree(process):
        terminated.append(process)
        process.alive = False

    with pytest.raises(OSError, match="simulated wait failure"):
        _wait_for_guarded_target(
            target,
            terminate_tree=terminate_tree,
            confirm_tree=lambda _process_group_id: None,
        )

    assert terminated == [target]
    assert target.wait_calls == 2


def test_guarded_target_uses_an_isolated_process_group_on_each_platform():
    from src.scripts.run_with_backend_runtime_lock import (
        _guarded_target_popen_kwargs,
    )

    windows_kwargs = _guarded_target_popen_kwargs("nt")
    posix_kwargs = _guarded_target_popen_kwargs("posix")

    assert windows_kwargs["creationflags"] & int(
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    )
    assert posix_kwargs == {"start_new_session": True}


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


def test_supervisor_death_before_child_self_lock_never_opens_exclusive_gap(tmp_path):
    lock_module = _lock_module()
    started_path = tmp_path / "child-started-before-self-lock.txt"
    allow_self_lock_path = tmp_path / "allow-child-self-lock.txt"
    child_locked_path = tmp_path / "child-self-locked.txt"
    stop_path = tmp_path / "child-stop.txt"
    done_path = tmp_path / "child-done.txt"
    child_source = """
import os
import pathlib
import sys
import time
from src.core.backend_runtime_lock import backend_runtime_lock

root = pathlib.Path(sys.argv[1])
started = pathlib.Path(sys.argv[2])
allow_self_lock = pathlib.Path(sys.argv[3])
child_locked = pathlib.Path(sys.argv[4])
stop = pathlib.Path(sys.argv[5])
done = pathlib.Path(sys.argv[6])
started.write_text(str(os.getpid()), encoding="utf-8")
while not allow_self_lock.exists():
    time.sleep(0.02)
with backend_runtime_lock(root, mode="shared", timeout_seconds=2):
    child_locked.write_text("locked", encoding="utf-8")
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
            str(started_path),
            str(allow_self_lock_path),
            str(child_locked_path),
            str(stop_path),
            str(done_path),
        ],
        env=_subprocess_environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    child_pid: int | None = None
    try:
        deadline = time.monotonic() + 5
        while not started_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert started_path.exists(), "child never reached the pre-self-lock window"
        child_pid = int(started_path.read_text(encoding="utf-8"))
        assert not child_locked_path.exists()

        supervisor.kill()
        supervisor.wait(timeout=5)
        with pytest.raises(TimeoutError, match="backend runtime lock"):
            with lock_module.backend_runtime_lock(tmp_path, timeout_seconds=0.2):
                pytest.fail(
                    "exclusive synchronization entered while a pre-self-lock child was alive"
                )
    finally:
        allow_self_lock_path.write_text("allow", encoding="utf-8")
        stop_path.write_text("stop", encoding="utf-8")
        deadline = time.monotonic() + 5
        while not done_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not done_path.exists():
            if supervisor.poll() is None:
                supervisor.kill()
                supervisor.wait(timeout=5)
            if child_pid is None and started_path.exists():
                child_pid = int(started_path.read_text(encoding="utf-8"))
            if child_pid is not None and os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(child_pid), "/F"],
                    capture_output=True,
                    check=False,
                )
            elif child_pid is not None:
                os.kill(child_pid, 15)

    assert child_locked_path.read_text(encoding="utf-8") == "locked"
    assert done_path.read_text(encoding="utf-8") == "done"
    with lock_module.backend_runtime_lock(tmp_path, timeout_seconds=2):
        assert lock_module.backend_runtime_lock_is_held(tmp_path)


def test_normal_target_exit_stops_descendants_before_exclusive_sync(tmp_path):
    lock_module = _lock_module()
    descendant_pid_path = tmp_path / "normal-exit-descendant.pid"
    allow_target_exit_path = tmp_path / "allow-normal-target-exit"
    descendant_source = """
import os
from pathlib import Path
import sys
import time

Path(sys.argv[1]).write_text(str(os.getpid()), encoding="utf-8")
time.sleep(30)
"""
    target_source = """
from pathlib import Path
import subprocess
import sys
import time

pid_path = Path(sys.argv[1])
descendant_source = sys.argv[2]
allow_exit = Path(sys.argv[3])
subprocess.Popen([sys.executable, "-c", descendant_source, str(pid_path)])
deadline = time.monotonic() + 5
while not pid_path.exists() and time.monotonic() < deadline:
    time.sleep(0.02)
if not pid_path.exists():
    raise SystemExit(3)
while not allow_exit.exists():
    time.sleep(0.02)
raise SystemExit(0)
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
            target_source,
            str(descendant_pid_path),
            descendant_source,
            str(allow_target_exit_path),
        ],
        env=_subprocess_environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    descendant = None
    descendant_created_at = None
    try:
        deadline = time.monotonic() + 5
        while not descendant_pid_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert descendant_pid_path.exists()
        descendant = psutil.Process(
            int(descendant_pid_path.read_text(encoding="utf-8"))
        )
        descendant_created_at = descendant.create_time()
        allow_target_exit_path.write_text("exit", encoding="utf-8")
        assert supervisor.wait(timeout=10) == 0

        with lock_module.backend_runtime_lock(tmp_path, timeout_seconds=2):
            try:
                survivor = psutil.Process(descendant.pid)
                descendant_is_alive = (
                    survivor.create_time() == descendant_created_at
                    and survivor.is_running()
                    and survivor.status() != psutil.STATUS_ZOMBIE
                )
            except psutil.NoSuchProcess:
                descendant_is_alive = False
            assert not descendant_is_alive, (
                "exclusive synchronization entered while a normal-exit target "
                "descendant was still alive"
            )
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
            supervisor.wait(timeout=5)
        if descendant is not None:
            try:
                survivor = psutil.Process(descendant.pid)
                if survivor.create_time() == descendant_created_at:
                    survivor.kill()
                    survivor.wait(timeout=5)
            except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                pass


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


def test_lock_file_symlink_is_rejected_before_external_target_is_extended(tmp_path):
    lock_module = _lock_module()
    external = tmp_path / "outside-lock-target.bin"
    external.write_bytes(b"outside")
    lock_path = lock_module.backend_runtime_lock_path(tmp_path)
    try:
        lock_path.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")

    with pytest.raises((OSError, ValueError), match="link|reparse|safe"):
        with lock_module.backend_runtime_lock(tmp_path, timeout_seconds=0.2):
            pytest.fail("linked lock file must never be acquired")

    assert external.read_bytes() == b"outside"


def test_lock_file_hardlink_is_rejected_before_external_target_is_extended(tmp_path):
    lock_module = _lock_module()
    external = tmp_path / "outside-lock-target.bin"
    external.write_bytes(b"outside")
    lock_path = lock_module.backend_runtime_lock_path(tmp_path)
    os.link(external, lock_path)

    with pytest.raises(ValueError, match="hard link|link count"):
        with lock_module.backend_runtime_lock(tmp_path, timeout_seconds=0.2):
            pytest.fail("hard-linked lock file must never be acquired")

    assert external.read_bytes() == b"outside"


def test_lock_file_swap_after_lstat_is_rejected_before_external_write(tmp_path):
    lock_module = _lock_module()
    lock_path = lock_module.backend_runtime_lock_path(tmp_path)
    lock_path.write_bytes(b"local")
    external = tmp_path / "outside-race-target.bin"
    external.write_bytes(b"outside")

    def swap_to_hardlink(stage: str, path: Path) -> None:
        if stage != "after_initial_lstat":
            return
        path.unlink()
        os.link(external, path)

    lock = lock_module.BackendRuntimeFileLock(
        lock_path,
        timeout_seconds=0.2,
        race_hook=swap_to_hardlink,
    )
    with pytest.raises((RuntimeError, ValueError), match="identity|hard link|link count"):
        lock.acquire()

    assert external.read_bytes() == b"outside"


def test_lock_and_retained_quarantine_artifacts_are_gitignored():
    gitignore = Path(".gitignore").read_text(encoding="utf-8")

    assert ".vantage-backend-runtime.lock" in gitignore
    assert ".venv-backend-runtime-gpu.quarantine-*/" in gitignore

import importlib.util
import io
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import psutil
import pytest


def _load_launcher_module():
    spec = importlib.util.spec_from_file_location(
        "run_frontend_background",
        "src/scripts/run_frontend_background.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _wait_for_path(path: Path, *, timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert path.exists(), f"timed out waiting for {path.name}"


def _process_identity(pid: int) -> tuple[int, float]:
    process = psutil.Process(pid)
    return process.pid, process.create_time()


def _identity_is_running(identity: tuple[int, float]) -> bool:
    pid, created_at = identity
    try:
        process = psutil.Process(pid)
        return (
            process.create_time() == created_at
            and process.is_running()
            and process.status() != psutil.STATUS_ZOMBIE
        )
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def _wait_for_identities_to_stop(
    identities: list[tuple[int, float]],
    *,
    timeout_seconds: float = 5.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while (
        any(_identity_is_running(identity) for identity in identities)
        and time.monotonic() < deadline
    ):
        time.sleep(0.02)
    survivors = [
        pid
        for pid, created_at in identities
        if _identity_is_running((pid, created_at))
    ]
    assert survivors == [], f"frontend lifecycle processes survived: {survivors}"


def _terminate_identities(identities: list[tuple[int, float]]) -> None:
    for identity in reversed(identities):
        if not _identity_is_running(identity):
            continue
        pid, _created_at = identity
        try:
            process = psutil.Process(pid)
            process.kill()
            process.wait(timeout=3)
        except (psutil.NoSuchProcess, psutil.TimeoutExpired, psutil.AccessDenied):
            pass


def _write_frontend_tree_fixture(tmp_path: Path) -> Path:
    target_script = tmp_path / "frontend-target.py"
    target_script.write_text(
        "\n".join(
            (
                "import os",
                "from pathlib import Path",
                "import subprocess",
                "import sys",
                "import time",
                "target_pid_path = Path(sys.argv[1])",
                "grandchild_pid_path = Path(sys.argv[2])",
                "grandchild_source = (",
                "    \"import os; from pathlib import Path; import sys; import time; \"",
                "    \"Path(sys.argv[1]).write_text(str(os.getpid()), encoding='utf-8'); \"",
                "    \"print('pipe-grandchild-ready', flush=True); time.sleep(60)\"",
                ")",
                "grandchild = subprocess.Popen(",
                "    [sys.executable, '-c', grandchild_source, str(grandchild_pid_path)],",
                "    stdin=subprocess.DEVNULL,",
                ")",
                "target_pid_path.write_text(str(os.getpid()), encoding='utf-8')",
                "print('target-ready', flush=True)",
                "time.sleep(60)",
            )
        ),
        encoding="utf-8",
    )
    return target_script


def _spawn_frontend_supervisor_fixture(
    tmp_path: Path,
    *,
    notify_behavior: str,
) -> tuple[subprocess.Popen, dict[str, Path]]:
    launcher_path = Path("src/scripts/run_frontend_background.py").resolve()
    target_script = _write_frontend_tree_fixture(tmp_path)
    paths = {
        "target_pid": tmp_path / "target.pid",
        "grandchild_pid": tmp_path / "grandchild.pid",
        "notify_entered": tmp_path / "notify-entered",
        "returncode": tmp_path / "supervisor.returncode",
    }
    worker_path = tmp_path / "frontend-supervisor-fixture.py"
    worker_path.write_text(
        "\n".join(
            (
                "import importlib.util",
                "import os",
                "from datetime import datetime",
                "from pathlib import Path",
                "import sys",
                "import time",
                "launcher_path = Path(sys.argv[1])",
                "root = Path(sys.argv[2])",
                "target_script = Path(sys.argv[3])",
                "target_pid_path = Path(sys.argv[4])",
                "grandchild_pid_path = Path(sys.argv[5])",
                "notify_path = Path(sys.argv[6])",
                "returncode_path = Path(sys.argv[7])",
                "notify_behavior = sys.argv[8]",
                "spec = importlib.util.spec_from_file_location('frontend_fixture', launcher_path)",
                "launcher = importlib.util.module_from_spec(spec)",
                "assert spec.loader is not None",
                "spec.loader.exec_module(launcher)",
                "runtime_logs = launcher._prepare_frontend_runtime_logs(",
                "    root / 'logs', 'production', datetime.now()",
                ")",
                "def notify_ready():",
                "    notify_path.write_text('entered', encoding='utf-8')",
                "    if notify_behavior == 'block':",
                "        while True:",
                "            time.sleep(1)",
                "    if notify_behavior == 'error':",
                "        time.sleep(0.5)",
                "        raise RuntimeError('injected notify failure')",
                "returncode = launcher._run_frontend_supervisor(",
                "    mode='production',",
                "    command=[",
                "        sys.executable, str(target_script),",
                "        str(target_pid_path), str(grandchild_pid_path),",
                "    ],",
                "    env=dict(os.environ),",
                "    webapp_dir=root,",
                "    runtime_logs=runtime_logs,",
                "    path_prefixes={'<PROJECT_ROOT>': root},",
                "    launched_at=datetime.now(),",
                "    notify_ready=notify_ready,",
                ")",
                "returncode_path.write_text(str(returncode), encoding='utf-8')",
                "raise SystemExit(returncode)",
            )
        ),
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [
            sys.executable,
            str(worker_path),
            str(launcher_path),
            str(tmp_path),
            str(target_script),
            str(paths["target_pid"]),
            str(paths["grandchild_pid"]),
            str(paths["notify_entered"]),
            str(paths["returncode"]),
            notify_behavior,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if os.name == "nt"
            else 0
        ),
        start_new_session=os.name != "nt",
        close_fds=True,
    )
    return process, paths


def _capture_frontend_tree(
    supervisor: subprocess.Popen,
    paths: dict[str, Path],
) -> tuple[list[tuple[int, float]], int, int, int]:
    supervisor_identity = _process_identity(supervisor.pid)
    for name in ("target_pid", "grandchild_pid", "notify_entered"):
        _wait_for_path(paths[name])
    target_pid = int(paths["target_pid"].read_text(encoding="utf-8"))
    grandchild_pid = int(paths["grandchild_pid"].read_text(encoding="utf-8"))
    deadline = time.monotonic() + 1
    owner_pid = None
    descendants = []
    while owner_pid is None and time.monotonic() < deadline:
        try:
            descendants = psutil.Process(supervisor.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            descendants = []
        candidates = []
        for child in descendants:
            try:
                if "--own-target" in child.cmdline():
                    candidates.append(child.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if candidates:
            owner_pid = candidates[0]
            break
        time.sleep(0.02)
    try:
        descendants = psutil.Process(supervisor.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        descendants = []
    discovered_pids = {
        target_pid,
        grandchild_pid,
        *(child.pid for child in descendants),
    }
    identities = [supervisor_identity]
    identities.extend(_process_identity(pid) for pid in sorted(discovered_pids))
    return identities, owner_pid or -1, target_pid, grandchild_pid


def test_build_frontend_command_uses_expected_npm_scripts():
    launcher = _load_launcher_module()

    production = launcher._build_frontend_command("production", npm_executable="npm.cmd")
    development = launcher._build_frontend_command("development", npm_executable="npm.cmd")

    assert production == ["npm.cmd", "run", "electron:start"]
    assert development == ["npm.cmd", "run", "electron:dev"]


def test_build_frontend_env_sets_only_needed_mode_flags():
    launcher = _load_launcher_module()

    production = launcher._build_frontend_env("production", {"FOO": "bar"})
    development = launcher._build_frontend_env("development", {"NODE_ENV": "production", "FOO": "bar"})

    assert production["NODE_ENV"] == "production"
    assert production["FOO"] == "bar"
    assert "NODE_ENV" not in development
    assert development["FOO"] == "bar"


def test_build_frontend_env_includes_runtime_path_contract():
    launcher = _load_launcher_module()
    runtime_env = {
        "VANTAGE_APP_MODE": "development",
        "VANTAGE_DATA_DIR": r"C:\Users\Example\AppData\Local\Vantage",
        "VANTAGE_LOG_DIR": r"C:\Users\Example\AppData\Local\Vantage\logs",
    }

    with patch.object(launcher.Config, "build_runtime_environment", return_value=runtime_env):
        production = launcher._build_frontend_env("production", {"FOO": "bar"})

    assert production["FOO"] == "bar"
    assert production["NODE_ENV"] == "production"
    assert production["VANTAGE_APP_MODE"] == "development"
    assert production["VANTAGE_DATA_DIR"] == runtime_env["VANTAGE_DATA_DIR"]
    assert production["VANTAGE_LOG_DIR"] == runtime_env["VANTAGE_LOG_DIR"]


def test_frontend_launcher_detaches_from_parent_session_on_posix():
    launcher = _load_launcher_module()

    with patch.object(launcher.os, "name", "posix"):
        assert launcher._get_start_new_session() is True

    with patch.object(launcher.os, "name", "nt"):
        assert launcher._get_start_new_session() is False


def test_ensure_project_root_on_sys_path_returns_repo_root():
    launcher = _load_launcher_module()

    repo_root = launcher._ensure_project_root_on_sys_path(
        script_path=Path("src/scripts/run_frontend_background.py").resolve(),
        path_list=[],
    )

    assert repo_root == Path("src/scripts/run_frontend_background.py").resolve().parents[2]


def test_prepare_frontend_runtime_logs_creates_timestamped_logs_and_latest_pointers(tmp_path):
    launcher = _load_launcher_module()
    logs_dir = tmp_path / "logs"
    launched_at = datetime(2026, 4, 22, 10, 30, 45)

    runtime_logs = launcher._prepare_frontend_runtime_logs(logs_dir, "production", launched_at)

    assert runtime_logs["stdout_log"] == logs_dir / "frontend" / "frontend-production-out-20260422_103045.log"
    assert runtime_logs["stderr_log"] == logs_dir / "frontend" / "frontend-production-err-20260422_103045.log"
    assert runtime_logs["stdout_pointer"] == logs_dir / "frontend_production.out.latest.log"
    assert runtime_logs["stderr_pointer"] == logs_dir / "frontend_production.err.latest.log"
    assert runtime_logs["stdout_pointer"].read_text(encoding="utf-8") == str(runtime_logs["stdout_log"].resolve())
    assert runtime_logs["stderr_pointer"].read_text(encoding="utf-8") == str(runtime_logs["stderr_log"].resolve())


def test_prepare_frontend_runtime_logs_does_not_reuse_legacy_fixed_logs(tmp_path):
    launcher = _load_launcher_module()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "frontend_production.out.log").write_text("legacy stdout\n", encoding="utf-8")
    (logs_dir / "frontend_production.err.log").write_text("legacy stderr\n", encoding="utf-8")

    runtime_logs = launcher._prepare_frontend_runtime_logs(
        logs_dir,
        "production",
        datetime(2026, 4, 22, 10, 31, 0),
    )

    assert runtime_logs["stdout_log"].name != "frontend_production.out.log"
    assert runtime_logs["stderr_log"].name != "frontend_production.err.log"


def test_frontend_supervisor_redacts_split_native_child_output(tmp_path):
    launcher = _load_launcher_module()
    logs_dir = tmp_path / "logs"
    runtime_logs = launcher._prepare_frontend_runtime_logs(
        logs_dir,
        "production",
        datetime(2026, 8, 11, 18, 0, 0),
    )
    private_root = tmp_path / "Private Frontend"
    private_root.mkdir()
    private_file = private_root / "electron-main.cjs"
    secret = "frontend-bearer-secret-1234567890"
    child_script = tmp_path / "child.py"
    child_script.write_text(
        "\n".join(
            (
                "import os",
                f"private_path = {str(private_file)!r}.encode('utf-8')",
                f"secret = {secret!r}.encode('utf-8')",
                "split = max(1, len(private_path) // 2)",
                "os.write(1, b'npm path=' + private_path[:split])",
                "os.write(1, private_path[split:] + b':42:7\\n')",
                "os.write(2, b'Authorization: Bea')",
                "os.write(2, b'rer ' + secret + b'\\n')",
            )
        ),
        encoding="utf-8",
    )
    ready_events = []

    returncode = launcher._run_frontend_supervisor(
        mode="production",
        command=[sys.executable, str(child_script)],
        env=dict(os.environ),
        webapp_dir=tmp_path,
        runtime_logs=runtime_logs,
        path_prefixes={"<PROJECT_ROOT>": private_root},
        launched_at=datetime(2026, 8, 11, 18, 0, 0),
        notify_ready=lambda: ready_events.append("ready"),
    )

    assert returncode == 0
    assert ready_events == ["ready"]
    stdout_text = runtime_logs["stdout_log"].read_text(encoding="utf-8")
    stderr_text = runtime_logs["stderr_log"].read_text(encoding="utf-8")
    assert str(private_root) not in stdout_text
    assert secret not in stderr_text
    assert "<PROJECT_ROOT>" in stdout_text
    assert "electron-main.cjs:42:7" in stdout_text
    assert "Authorization: Bearer [REDACTED_TOKEN]" in stderr_text


def test_frontend_launcher_detaches_a_long_lived_redacting_supervisor(tmp_path):
    launcher = _load_launcher_module()
    project_root = tmp_path / "project"
    webapp_dir = project_root / "src" / "webapp"
    webapp_dir.mkdir(parents=True)
    logs_dir = tmp_path / "logs"
    process = SimpleNamespace(pid=4321, stdout=io.BytesIO(b"READY\n"))

    with (
        patch.object(launcher.Config, "get_project_root", return_value=project_root),
        patch.object(launcher.Config, "get_logs_dir", return_value=logs_dir),
        patch.object(launcher.subprocess, "Popen", return_value=process) as popen,
    ):
        assert launcher.main(["production"]) == 0

    command = popen.call_args.args[0]
    assert command[0] == sys.executable
    assert Path(command[1]).resolve() == Path(launcher.__file__).resolve()
    assert command[2:] == ["--supervise", "production"]
    assert popen.call_args.kwargs["stdin"] is subprocess.DEVNULL
    assert popen.call_args.kwargs["stdout"] is subprocess.PIPE
    assert popen.call_args.kwargs["stderr"] is subprocess.DEVNULL
    assert popen.call_args.kwargs["close_fds"] is True


def test_frontend_launcher_reports_real_supervisor_start_failure_without_private_paths(
    tmp_path,
):
    project_root = tmp_path / "Private Project"
    webapp_dir = project_root / "src" / "webapp"
    webapp_dir.mkdir(parents=True)
    runtime_root = tmp_path / "runtime-data"
    logs_dir = runtime_root / "logs"
    environment = {
        **os.environ,
        "PATH": "",
        "VANTAGE_PROJECT_ROOT": str(project_root),
        "VANTAGE_DATA_DIR": str(runtime_root),
        "VANTAGE_CONFIG_DIR": str(runtime_root / "config"),
        "VANTAGE_HISTORY_DIR": str(runtime_root / "history"),
        "VANTAGE_LOG_DIR": str(logs_dir),
        "VANTAGE_PLOT_DIR": str(runtime_root / "plots"),
        "VANTAGE_CACHE_DIR": str(runtime_root / "cache"),
        "VANTAGE_RUNTIME_DIR": str(runtime_root / "runtime"),
        "VANTAGE_MIGRATION_DIR": str(runtime_root / "migration"),
    }

    result = subprocess.run(
        [sys.executable, "src/scripts/run_frontend_background.py", "production"],
        cwd=Path.cwd(),
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )

    deadline = time.monotonic() + 5
    pointer = logs_dir / "frontend_production.err.latest.log"
    while not pointer.exists() and time.monotonic() < deadline:
        time.sleep(0.02)

    assert result.returncode != 0
    assert pointer.exists()
    persisted = Path(pointer.read_text(encoding="utf-8")).read_text(encoding="utf-8")
    assert str(project_root) not in persisted
    assert "Frontend process failed:" in persisted


def test_frontend_ready_timeout_terminates_supervisor_and_pipe_descendants(tmp_path):
    launcher = _load_launcher_module()
    child_pid_path = tmp_path / "child.pid"
    supervisor_source = "\n".join(
        (
            "import pathlib",
            "import subprocess",
            "import sys",
            "import time",
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])",
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8')",
            "time.sleep(30)",
        )
    )
    supervisor = subprocess.Popen(
        [sys.executable, "-c", supervisor_source, str(child_pid_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=launcher._get_creationflags(),
        start_new_session=launcher._get_start_new_session(),
        close_fds=True,
    )
    deadline = time.monotonic() + 5
    while not child_pid_path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert child_pid_path.exists(), "supervisor did not start its pipe-inheriting child"
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))

    signal = launcher._wait_for_supervisor_signal(
        supervisor,
        timeout_seconds=0.2,
    )
    if supervisor.stdout is not None:
        supervisor.stdout.close()

    assert signal == b""
    assert supervisor.poll() is not None
    deadline = time.monotonic() + 5
    while psutil.pid_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not psutil.pid_exists(child_pid)


def test_ready_supervisor_kill_stops_owner_target_and_pipe_grandchild(tmp_path):
    supervisor, paths = _spawn_frontend_supervisor_fixture(
        tmp_path,
        notify_behavior="ready",
    )
    identities = []
    try:
        identities, owner_pid, target_pid, grandchild_pid = _capture_frontend_tree(
            supervisor,
            paths,
        )

        supervisor.kill()
        supervisor.wait(timeout=5)
        _wait_for_identities_to_stop(identities)

        assert owner_pid not in (-1, target_pid, grandchild_pid)
        assert len(identities) >= 4
    finally:
        _terminate_identities(identities)


def test_supervisor_kill_while_notify_blocks_stops_the_owned_process_tree(tmp_path):
    supervisor, paths = _spawn_frontend_supervisor_fixture(
        tmp_path,
        notify_behavior="block",
    )
    identities = []
    try:
        identities, owner_pid, target_pid, grandchild_pid = _capture_frontend_tree(
            supervisor,
            paths,
        )

        supervisor.kill()
        supervisor.wait(timeout=5)
        _wait_for_identities_to_stop(identities)

        assert owner_pid not in (-1, target_pid, grandchild_pid)
        assert len(identities) >= 4
    finally:
        _terminate_identities(identities)


def test_notify_failure_stops_owner_target_and_pipe_grandchild(tmp_path):
    supervisor, paths = _spawn_frontend_supervisor_fixture(
        tmp_path,
        notify_behavior="error",
    )
    identities = []
    try:
        identities, owner_pid, target_pid, grandchild_pid = _capture_frontend_tree(
            supervisor,
            paths,
        )

        assert supervisor.wait(timeout=10) == 1
        _wait_for_identities_to_stop(identities)

        assert paths["returncode"].read_text(encoding="utf-8") == "1"
        assert owner_pid not in (-1, target_pid, grandchild_pid)
        assert len(identities) >= 4
    finally:
        _terminate_identities(identities)


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal-owned process groups")
def test_posix_owner_sigterm_stops_target_and_pipe_grandchild(tmp_path):
    supervisor, paths = _spawn_frontend_supervisor_fixture(
        tmp_path,
        notify_behavior="ready",
    )
    identities = []
    try:
        identities, owner_pid, target_pid, grandchild_pid = _capture_frontend_tree(
            supervisor,
            paths,
        )
        assert owner_pid not in (-1, target_pid, grandchild_pid)

        os.kill(owner_pid, signal.SIGTERM)
        _wait_for_identities_to_stop(identities)
    finally:
        _terminate_identities(identities)

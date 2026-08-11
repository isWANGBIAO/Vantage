import importlib.util
import io
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import psutil


def _load_launcher_module():
    spec = importlib.util.spec_from_file_location(
        "run_frontend_background",
        "src/scripts/run_frontend_background.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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

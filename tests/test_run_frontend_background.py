import importlib.util
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


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

    returncode = launcher._run_frontend_supervisor(
        mode="production",
        command=[sys.executable, str(child_script)],
        env=dict(os.environ),
        webapp_dir=tmp_path,
        runtime_logs=runtime_logs,
        path_prefixes={"<PROJECT_ROOT>": private_root},
        launched_at=datetime(2026, 8, 11, 18, 0, 0),
    )

    assert returncode == 0
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
    process = SimpleNamespace(pid=4321)

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
    assert popen.call_args.kwargs["stdout"] is subprocess.DEVNULL
    assert popen.call_args.kwargs["stderr"] is subprocess.DEVNULL
    assert popen.call_args.kwargs["close_fds"] is True

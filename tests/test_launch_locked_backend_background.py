from pathlib import Path
from types import SimpleNamespace


def test_locked_backend_background_command_uses_bootstrap_supervisor_and_runtime_python(
    tmp_path,
):
    from src.scripts.launch_locked_backend_background import build_locked_backend_command

    command = build_locked_backend_command(
        project_root=tmp_path,
        lock_runner=tmp_path / "src" / "scripts" / "run_with_backend_runtime_lock.py",
        backend_python=tmp_path / ".venv-backend-runtime-gpu" / "Scripts" / "python.exe",
        bootstrap_python="bootstrap-python",
    )

    assert command == [
        "bootstrap-python",
        str(tmp_path / "src" / "scripts" / "run_with_backend_runtime_lock.py"),
        "--project-root",
        str(tmp_path),
        "--",
        str(tmp_path / ".venv-backend-runtime-gpu" / "Scripts" / "python.exe"),
        "src/scripts/run_server_background.py",
    ]


def test_locked_backend_background_launch_is_detached_and_returns_pid(tmp_path):
    from src.scripts.launch_locked_backend_background import launch_locked_backend_background

    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(pid=4321)

    process = launch_locked_backend_background(
        project_root=tmp_path,
        lock_runner=tmp_path / "lock.py",
        backend_python=tmp_path / "runtime-python.exe",
        bootstrap_python="bootstrap-python",
        popen=fake_popen,
        platform_name="nt",
    )

    assert process.pid == 4321
    command, kwargs = calls[0]
    assert command[0] == "bootstrap-python"
    assert kwargs["cwd"] == str(Path(tmp_path))
    assert kwargs["stdin"] is not None
    assert kwargs["stdout"] is not None
    assert kwargs["stderr"] is not None
    assert kwargs["close_fds"] is True
    assert kwargs["start_new_session"] is False
    assert kwargs["creationflags"] != 0

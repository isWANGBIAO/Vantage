import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _ensure_project_root_on_sys_path(
    script_path: str | Path | None = None,
    path_list: list[str] | None = None,
) -> Path:
    current_script = Path(script_path or __file__).resolve()
    project_root = current_script.parents[2]
    resolved_path_list = path_list if path_list is not None else sys.path
    project_root_str = str(project_root)
    if project_root_str not in resolved_path_list:
        resolved_path_list.insert(0, project_root_str)
    return project_root


_ensure_project_root_on_sys_path()

from src.core.config import Config


def _resolve_npm_executable() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def _build_frontend_command(mode: str, npm_executable: str | None = None) -> list[str]:
    resolved_npm = npm_executable or _resolve_npm_executable()
    if mode == "production":
        return [resolved_npm, "run", "electron:start"]
    if mode == "development":
        return [resolved_npm, "run", "electron:dev"]
    raise ValueError(f"Unsupported frontend launch mode: {mode}")


def _build_frontend_env(mode: str, base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env or os.environ)
    env.update(Config.build_runtime_environment())
    if mode == "production":
        env["NODE_ENV"] = "production"
    else:
        env.pop("NODE_ENV", None)
    return env


def _get_creationflags() -> int:
    if os.name != "nt":
        return 0

    flags = 0
    for flag_name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        flags |= getattr(subprocess, flag_name, 0)
    return flags


def _get_start_new_session() -> bool:
    return os.name != "nt"


def _prepare_frontend_runtime_logs(logs_dir: Path, mode: str, launched_at: datetime) -> dict[str, Path]:
    runtime_dir = logs_dir / "frontend"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    timestamp = launched_at.strftime("%Y%m%d_%H%M%S")

    stdout_log = runtime_dir / f"frontend-{mode}-out-{timestamp}.log"
    stderr_log = runtime_dir / f"frontend-{mode}-err-{timestamp}.log"
    stdout_pointer = logs_dir / f"frontend_{mode}.out.latest.log"
    stderr_pointer = logs_dir / f"frontend_{mode}.err.latest.log"

    for pointer_path, log_path in (
        (stdout_pointer, stdout_log),
        (stderr_pointer, stderr_log),
    ):
        try:
            pointer_path.write_text(str(log_path.resolve()), encoding="utf-8")
        except OSError:
            pass

    return {
        "stdout_log": stdout_log,
        "stderr_log": stderr_log,
        "stdout_pointer": stdout_pointer,
        "stderr_pointer": stderr_pointer,
    }


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    mode = args[0] if args else "production"

    project_root = Config.get_project_root()
    webapp_dir = project_root / "src" / "webapp"
    logs_dir = Config.get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)

    launched_at = datetime.now()
    runtime_logs = _prepare_frontend_runtime_logs(logs_dir, mode, launched_at)
    stdout_log = runtime_logs["stdout_log"]
    stderr_log = runtime_logs["stderr_log"]
    timestamp = launched_at.isoformat()

    command = _build_frontend_command(mode)
    env = _build_frontend_env(mode)
    creationflags = _get_creationflags()

    with open(stdout_log, "a", encoding="utf-8") as stdout_handle, open(
        stderr_log, "a", encoding="utf-8"
    ) as stderr_handle:
        stdout_handle.write(f"\n=== Frontend launch {mode} {timestamp} ===\n")
        stderr_handle.write(f"\n=== Frontend launch {mode} {timestamp} ===\n")

        process = subprocess.Popen(
            command,
            cwd=webapp_dir,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=creationflags,
            start_new_session=_get_start_new_session(),
            close_fds=True,
        )

    print(f"Frontend launch requested: mode={mode}, pid={process.pid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

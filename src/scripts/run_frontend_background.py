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
from src.utils.sensitive_data import RedactingPipeLog, build_log_path_prefixes


SUPERVISE_ARG = "--supervise"


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


def _run_frontend_supervisor(
    *,
    mode: str,
    command: list[str],
    env: dict[str, str],
    webapp_dir: Path,
    runtime_logs: dict[str, Path],
    path_prefixes: dict[str, str],
    launched_at: datetime,
) -> int:
    """Run the frontend for its full lifetime while redacting persisted output."""

    timestamp = launched_at.isoformat()
    with RedactingPipeLog(
        runtime_logs["stdout_log"],
        path_prefixes=path_prefixes,
    ) as stdout_log, RedactingPipeLog(
        runtime_logs["stderr_log"],
        path_prefixes=path_prefixes,
    ) as stderr_log:
        header = f"\n=== Frontend launch {mode} {timestamp} ===\n"
        stdout_log.write_record(header)
        stderr_log.write_record(header)
        try:
            with stdout_log.capture_subprocess_output(
                stream_name="frontend-stdout"
            ) as stdout_handle, stderr_log.capture_subprocess_output(
                stream_name="frontend-stderr"
            ) as stderr_handle:
                process = subprocess.Popen(
                    command,
                    cwd=webapp_dir,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    creationflags=0,
                    start_new_session=False,
                    close_fds=True,
                )
                return process.wait()
        except Exception as exc:
            stderr_log.write_record(f"Frontend process failed: {exc}\n")
            return 1


def _supervise_frontend(mode: str) -> int:
    project_root = Config.get_project_root()
    webapp_dir = project_root / "src" / "webapp"
    runtime_paths = Config.get_runtime_paths()
    launched_at = datetime.now()
    runtime_logs = _prepare_frontend_runtime_logs(
        runtime_paths["log_dir"],
        mode,
        launched_at,
    )
    return _run_frontend_supervisor(
        mode=mode,
        command=_build_frontend_command(mode),
        env=_build_frontend_env(mode),
        webapp_dir=webapp_dir,
        runtime_logs=runtime_logs,
        path_prefixes=build_log_path_prefixes(
            project_root=project_root,
            runtime_paths=runtime_paths,
        ),
        launched_at=launched_at,
    )


def _launch_frontend_supervisor(mode: str) -> int:
    project_root = Config.get_project_root()
    command = [sys.executable, str(Path(__file__).resolve()), SUPERVISE_ARG, mode]
    process = subprocess.Popen(
        command,
        cwd=project_root,
        env=_build_frontend_env(mode),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_get_creationflags(),
        start_new_session=_get_start_new_session(),
        close_fds=True,
    )
    print(f"Frontend supervisor launched: mode={mode}, pid={process.pid}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if args and args[0] == SUPERVISE_ARG:
        mode = args[1] if len(args) > 1 else "production"
        return _supervise_frontend(mode)
    mode = args[0] if args else "production"
    _build_frontend_command(mode)
    return _launch_frontend_supervisor(mode)


if __name__ == "__main__":
    raise SystemExit(main())

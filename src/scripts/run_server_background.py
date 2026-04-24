import os
import runpy
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
from src.core.runtime_library_bootstrap import apply_runtime_library_dirs, preload_torch_libraries


RUN_PROMPT_BRIDGE_ARG = "--run-prompt"


def _redirect_standard_streams(log_path: Path):
    log_file = open(log_path, "a", encoding="utf-8", buffering=1)
    os.dup2(log_file.fileno(), 1)
    os.dup2(log_file.fileno(), 2)
    sys.stdout = open(1, "w", encoding="utf-8", buffering=1, closefd=False)
    sys.stderr = open(2, "w", encoding="utf-8", buffering=1, closefd=False)
    return log_file


def _prepare_server_runtime_log(logs_dir: Path, launched_at: datetime):
    runtime_dir = logs_dir / "server"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path = runtime_dir / f"server-{launched_at.strftime('%Y%m%d_%H%M%S')}.log"
    latest_pointer = logs_dir / "server.latest.log"
    try:
        latest_pointer.write_text(str(log_path.resolve()), encoding="utf-8")
    except OSError:
        pass
    return log_path, latest_pointer


def _resolve_runtime_context():
    runtime_paths = Config.get_runtime_paths()
    return {
        "project_root": Config.get_project_root(),
        "log_dir": runtime_paths["log_dir"],
        "env": Config.build_runtime_environment(),
    }


def _configure_frozen_runtime_search_paths(
    resource_root: Path,
    *,
    env: dict[str, str] | None = None,
    add_dll_directory=None,
):
    return apply_runtime_library_dirs(
        resource_root,
        env=env,
        add_dll_directory=add_dll_directory,
    )


def _preload_frozen_torch_libraries(
    resource_root: Path,
    *,
    load_library=None,
):
    return preload_torch_libraries(
        resource_root,
        load_library=load_library,
    )


def _run_server_entrypoint(
    project_root: Path,
    *,
    is_frozen: bool | None = None,
    run_path=runpy.run_path,
    server_main=None,
):
    frozen_mode = getattr(sys, "frozen", False) if is_frozen is None else is_frozen
    if frozen_mode:
        _configure_frozen_runtime_search_paths(project_root)
        _preload_frozen_torch_libraries(project_root)
        resolved_server_main = server_main
        if resolved_server_main is None:
            from src.server import main as resolved_server_main

        resolved_server_main()
        return "frozen"

    run_path(str(project_root / "src" / "server.py"), run_name="__main__")
    return "script"


def _run_prompt_entrypoint(args: list[str], *, run_prompt_main=None):
    if getattr(sys, "frozen", False):
        resource_root = Config.get_project_root()
        _configure_frozen_runtime_search_paths(resource_root)
        _preload_frozen_torch_libraries(resource_root)

    resolved_run_prompt_main = run_prompt_main
    if resolved_run_prompt_main is None:
        from src.scripts.run_prompt import main as resolved_run_prompt_main

    previous_argv = sys.argv[:]
    try:
        sys.argv = ["run_prompt.py", *args]
        resolved_run_prompt_main()
    finally:
        sys.argv = previous_argv


def main():
    if len(sys.argv) > 1 and sys.argv[1] == RUN_PROMPT_BRIDGE_ARG:
        _run_prompt_entrypoint(sys.argv[2:])
        return

    launched_at = datetime.now()
    runtime_context = _resolve_runtime_context()
    project_root = runtime_context["project_root"]
    logs_dir = runtime_context["log_dir"]
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path, _ = _prepare_server_runtime_log(logs_dir, launched_at)

    banner = f"\n=== Background server launch {launched_at.isoformat()} ===\n"
    with open(log_path, "a", encoding="utf-8") as bootstrap_log:
        bootstrap_log.write(banner)

    os.environ.update(runtime_context["env"])
    os.chdir(project_root)
    _redirect_standard_streams(log_path)
    _run_server_entrypoint(project_root)


if __name__ == "__main__":
    main()

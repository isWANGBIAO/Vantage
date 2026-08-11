import importlib
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


PROJECT_ROOT = _ensure_project_root_on_sys_path()

from src.core.config import Config
from src.core.runtime_library_bootstrap import apply_runtime_library_dirs
from src.utils.sensitive_data import RedactingTextStream


RUN_PROMPT_BRIDGE_ARG = "--run-prompt"
PACKAGED_RUNTIME_REQUIRED_IMPORTS = (
    "chinese_calendar",
    "zhdate",
)


def _redirect_standard_streams(log_path: Path, *, path_prefixes=None):
    log_file = open(log_path, "a", encoding="utf-8", buffering=1)
    os.dup2(log_file.fileno(), 1)
    os.dup2(log_file.fileno(), 2)
    sys.stdout = RedactingTextStream(
        open(1, "w", encoding="utf-8", buffering=1, closefd=False),
        path_prefixes=path_prefixes,
    )
    sys.stderr = RedactingTextStream(
        open(2, "w", encoding="utf-8", buffering=1, closefd=False),
        path_prefixes=path_prefixes,
    )
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


def _build_log_path_prefixes(
    *,
    project_root: Path,
    runtime_paths: dict,
    executable: str | Path | None = None,
    user_home: str | Path | None = None,
):
    prefixes = {}

    def add(label, value):
        if value is None:
            return
        try:
            value_text = os.fspath(value)
        except TypeError:
            return
        if value_text:
            prefixes[label] = value_text

    add("<PROJECT_ROOT>", project_root)
    for runtime_key, label in (
        ("config_dir", "<CONFIG_DIR>"),
        ("history_dir", "<HISTORY_DIR>"),
        ("log_dir", "<LOG_DIR>"),
        ("plot_dir", "<PLOT_DIR>"),
        ("cache_dir", "<CACHE_DIR>"),
        ("runtime_dir", "<RUNTIME_DIR>"),
        ("migration_dir", "<MIGRATION_DIR>"),
        ("data_dir", "<DATA_DIR>"),
    ):
        add(label, runtime_paths.get(runtime_key))
    resolved_executable = Path(executable or sys.executable)
    add("<EXECUTABLE_DIR>", resolved_executable.parent)
    add("<USER_HOME>", user_home or Path.home())
    return prefixes


def _resolve_runtime_context():
    runtime_paths = Config.get_runtime_paths()
    project_root = Config.get_project_root()
    return {
        "project_root": project_root,
        "log_dir": runtime_paths["log_dir"],
        "env": Config.build_runtime_environment(),
        "path_prefixes": _build_log_path_prefixes(
            project_root=project_root,
            runtime_paths=runtime_paths,
        ),
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


def _validate_packaged_runtime_imports(*, import_module=importlib.import_module):
    missing = []
    for module_name in PACKAGED_RUNTIME_REQUIRED_IMPORTS:
        try:
            import_module(module_name)
        except Exception as exc:
            missing.append(f"{module_name} ({exc})")

    if missing:
        raise RuntimeError("Missing packaged runtime module(s): " + ", ".join(missing))


def _run_server_entrypoint(
    project_root: Path,
    *,
    is_frozen: bool | None = None,
    run_path=runpy.run_path,
    server_main=None,
    validate_runtime_imports=_validate_packaged_runtime_imports,
):
    frozen_mode = getattr(sys, "frozen", False) if is_frozen is None else is_frozen
    if frozen_mode:
        _configure_frozen_runtime_search_paths(project_root)
        validate_runtime_imports()
        resolved_server_main = server_main
        if resolved_server_main is None:
            from src.server import main as resolved_server_main

        resolved_server_main()
        return "frozen"

    run_path(str(project_root / "src" / "server.py"), run_name="__main__")
    return "script"


def _run_prompt_entrypoint(
    args: list[str],
    *,
    run_prompt_main=None,
    validate_runtime_imports=_validate_packaged_runtime_imports,
):
    if getattr(sys, "frozen", False):
        resource_root = Config.get_project_root()
        _configure_frozen_runtime_search_paths(resource_root)
        validate_runtime_imports()

    resolved_run_prompt_main = run_prompt_main
    if resolved_run_prompt_main is None:
        from src.scripts.run_prompt import main as resolved_run_prompt_main

    previous_argv = sys.argv[:]
    try:
        sys.argv = ["run_prompt.py", *args]
        resolved_run_prompt_main()
    finally:
        sys.argv = previous_argv


def _main_without_backend_runtime_lock():
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
    _redirect_standard_streams(
        log_path,
        path_prefixes=runtime_context["path_prefixes"],
    )
    _run_server_entrypoint(project_root)


def main():
    if getattr(sys, "frozen", False):
        return _main_without_backend_runtime_lock()

    from src.core.backend_runtime_lock import (
        backend_runtime_lock,
    )

    with backend_runtime_lock(PROJECT_ROOT, mode="shared"):
        return _main_without_backend_runtime_lock()


if __name__ == "__main__":
    main()

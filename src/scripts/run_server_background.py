import os
import runpy
import sys
import ctypes
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

_RUNTIME_DLL_HANDLES = []


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
    resolved_env = env if env is not None else os.environ
    resolved_add_dll_directory = add_dll_directory
    if resolved_add_dll_directory is None:
        resolved_add_dll_directory = getattr(os, "add_dll_directory", None)

    base_roots = []
    internal_root = resource_root / "_internal"
    if internal_root.exists():
        base_roots.append(internal_root)
    base_roots.append(resource_root)

    candidate_dirs = []
    for base_root in base_roots:
        candidate_dirs.extend(
            [
                base_root,
                base_root / "torch" / "lib",
                base_root / "onnxruntime" / "capi",
            ]
        )

    seen_dirs = set()
    existing_dirs = []
    for directory in candidate_dirs:
        if not directory.exists():
            continue
        directory_str = str(directory.resolve())
        if directory_str in seen_dirs:
            continue
        seen_dirs.add(directory_str)
        existing_dirs.append(directory.resolve())
    if not existing_dirs:
        return []

    existing_path_entries = [entry for entry in resolved_env.get("PATH", "").split(os.pathsep) if entry]
    new_entries = [str(directory) for directory in existing_dirs]
    resolved_env["PATH"] = os.pathsep.join(new_entries + existing_path_entries)

    if resolved_add_dll_directory is not None:
        for directory in existing_dirs:
            handle = resolved_add_dll_directory(str(directory))
            if handle is not None:
                _RUNTIME_DLL_HANDLES.append(handle)

    return new_entries


def _preload_frozen_torch_libraries(
    resource_root: Path,
    *,
    load_library=None,
):
    resolved_loader = load_library or ctypes.CDLL
    candidate_roots = []
    internal_root = resource_root / "_internal"
    if internal_root.exists():
        candidate_roots.append(internal_root)
    candidate_roots.append(resource_root)

    torch_lib_dir = None
    for candidate_root in candidate_roots:
        candidate_torch_lib = candidate_root / "torch" / "lib"
        if candidate_torch_lib.exists():
            torch_lib_dir = candidate_torch_lib
            break

    if torch_lib_dir is None:
        return []

    preload_order = [
        "torch_global_deps.dll",
        "c10.dll",
        "c10_cuda.dll",
        "torch_cpu.dll",
        "torch_cuda.dll",
        "torch_python.dll",
    ]
    loaded_dlls = []
    for dll_name in preload_order:
        dll_path = torch_lib_dir / dll_name
        if not dll_path.exists():
            continue
        try:
            resolved_loader(str(dll_path))
            loaded_dlls.append(str(dll_path))
        except Exception:  # noqa: BLE001
            continue

    return loaded_dlls


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


def main():
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

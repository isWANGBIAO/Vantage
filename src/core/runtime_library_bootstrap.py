from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path


_RUNTIME_DLL_HANDLES = []

_INTERNAL_RELATIVE_DIRS = (
    Path("torch") / "lib",
    Path("onnxruntime") / "capi",
    Path("torchaudio") / "lib",
    Path("mediapipe"),
    Path("cv2"),
    Path("numpy.libs"),
    Path("scipy.libs"),
    Path("pandas.libs"),
    Path("pyzmq.libs"),
    Path("pywin32_system32"),
)

_TORCH_PRELOAD_ORDER = (
    "torch_global_deps.dll",
    "c10.dll",
    "c10_cuda.dll",
    "torch_cpu.dll",
    "torch_cuda.dll",
    "torch_python.dll",
)


def resolve_runtime_library_root(resource_root: str | Path | None = None) -> Path:
    if resource_root:
        return Path(resource_root).resolve()

    meipass_root = getattr(sys, "_MEIPASS", None)
    if meipass_root:
        return Path(meipass_root).resolve()

    return Path(sys.executable).resolve().parent


def _resolve_internal_and_runtime_roots(resource_root: str | Path | None) -> tuple[Path, Path]:
    resolved_root = resolve_runtime_library_root(resource_root)
    if resolved_root.name == "_internal":
        return resolved_root, resolved_root.parent

    internal_root = resolved_root / "_internal"
    if internal_root.exists():
        return internal_root.resolve(), resolved_root

    return resolved_root, resolved_root


def collect_runtime_library_dirs(resource_root: str | Path | None) -> list[Path]:
    internal_root, runtime_root = _resolve_internal_and_runtime_roots(resource_root)
    candidate_dirs = [internal_root]
    if runtime_root != internal_root:
        candidate_dirs.append(runtime_root)

    for relative_dir in _INTERNAL_RELATIVE_DIRS:
        candidate_dirs.append(internal_root / relative_dir)

    resolved_dirs = []
    seen = set()
    for directory in candidate_dirs:
        if not directory.exists():
            continue
        resolved_dir = directory.resolve()
        if resolved_dir in seen:
            continue
        seen.add(resolved_dir)
        resolved_dirs.append(resolved_dir)
    return resolved_dirs


def apply_runtime_library_dirs(
    resource_root: str | Path | None,
    *,
    env: dict[str, str] | None = None,
    add_dll_directory=None,
) -> list[str]:
    resolved_env = env if env is not None else os.environ
    resolved_add_dll_directory = add_dll_directory
    if resolved_add_dll_directory is None:
        resolved_add_dll_directory = getattr(os, "add_dll_directory", None)

    runtime_dirs = collect_runtime_library_dirs(resource_root)
    if not runtime_dirs:
        return []

    existing_path_entries = [entry for entry in resolved_env.get("PATH", "").split(os.pathsep) if entry]
    new_entries = [str(directory) for directory in runtime_dirs]
    resolved_env["PATH"] = os.pathsep.join(new_entries + existing_path_entries)

    if resolved_add_dll_directory is not None:
        for directory in runtime_dirs:
            handle = resolved_add_dll_directory(str(directory))
            if handle is not None:
                _RUNTIME_DLL_HANDLES.append(handle)

    return new_entries


def preload_torch_libraries(
    resource_root: str | Path | None,
    *,
    load_library=None,
) -> list[str]:
    resolved_loader = load_library or ctypes.CDLL
    internal_root, _runtime_root = _resolve_internal_and_runtime_roots(resource_root)
    torch_lib_dir = internal_root / "torch" / "lib"
    if not torch_lib_dir.exists():
        return []

    loaded_dlls = []
    for dll_name in _TORCH_PRELOAD_ORDER:
        dll_path = torch_lib_dir / dll_name
        if not dll_path.exists():
            continue
        try:
            resolved_loader(str(dll_path))
            loaded_dlls.append(str(dll_path))
        except Exception:
            continue
    return loaded_dlls


def bootstrap_packaged_runtime_libraries(
    resource_root: str | Path | None = None,
    *,
    env: dict[str, str] | None = None,
    add_dll_directory=None,
    load_library=None,
) -> dict[str, object]:
    resolved_root = resolve_runtime_library_root(resource_root)
    library_dirs = apply_runtime_library_dirs(
        resolved_root,
        env=env,
        add_dll_directory=add_dll_directory,
    )
    preloaded_dlls = preload_torch_libraries(
        resolved_root,
        load_library=load_library,
    )
    return {
        "resource_root": str(resolved_root),
        "library_dirs": library_dirs,
        "preloaded_dlls": preloaded_dlls,
    }

from pathlib import Path

from src.core.runtime_library_bootstrap import (
    collect_runtime_library_dirs,
    preload_torch_libraries,
)


def test_collect_runtime_library_dirs_prefers_internal_native_dirs(tmp_path):
    runtime_root = tmp_path / "VantageBackend"
    internal_root = runtime_root / "_internal"
    torch_lib = internal_root / "torch" / "lib"
    onnx_capi = internal_root / "onnxruntime" / "capi"
    numpy_libs = internal_root / "numpy.libs"
    pywin32_system32 = internal_root / "pywin32_system32"

    torch_lib.mkdir(parents=True)
    onnx_capi.mkdir(parents=True)
    numpy_libs.mkdir(parents=True)
    pywin32_system32.mkdir(parents=True)

    resolved_dirs = collect_runtime_library_dirs(runtime_root)

    assert resolved_dirs[:5] == [
        internal_root,
        runtime_root,
        torch_lib,
        onnx_capi,
        numpy_libs,
    ]
    assert pywin32_system32 in resolved_dirs
    assert internal_root / "torchaudio" / "lib" not in resolved_dirs


def test_preload_torch_libraries_uses_internal_torch_lib_when_runtime_root_passed(tmp_path):
    runtime_root = tmp_path / "VantageBackend"
    torch_lib = runtime_root / "_internal" / "torch" / "lib"
    torch_lib.mkdir(parents=True)

    for dll_name in ("torch_global_deps.dll", "c10.dll", "torch_cpu.dll"):
        (torch_lib / dll_name).write_bytes(b"dll")

    loaded = []

    preload_torch_libraries(
        runtime_root,
        load_library=lambda value: loaded.append(Path(value).name),
    )

    assert loaded == [
        "torch_global_deps.dll",
        "c10.dll",
        "torch_cpu.dll",
    ]

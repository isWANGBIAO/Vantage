from pathlib import Path

from src.core.runtime_library_bootstrap import collect_runtime_library_dirs


def test_collect_runtime_library_dirs_prefers_internal_native_dirs(tmp_path):
    runtime_root = tmp_path / "VantageBackend"
    internal_root = runtime_root / "_internal"
    cv2_lib = internal_root / "cv2"
    numpy_libs = internal_root / "numpy.libs"
    pywin32_system32 = internal_root / "pywin32_system32"
    obsolete_torch_lib = internal_root / "torch" / "lib"
    obsolete_onnx_capi = internal_root / "onnxruntime" / "capi"

    cv2_lib.mkdir(parents=True)
    numpy_libs.mkdir(parents=True)
    pywin32_system32.mkdir(parents=True)
    obsolete_torch_lib.mkdir(parents=True)
    obsolete_onnx_capi.mkdir(parents=True)

    resolved_dirs = collect_runtime_library_dirs(runtime_root)

    assert resolved_dirs[:4] == [
        internal_root,
        runtime_root,
        cv2_lib,
        numpy_libs,
    ]
    assert pywin32_system32 in resolved_dirs
    assert obsolete_torch_lib not in resolved_dirs
    assert obsolete_onnx_capi not in resolved_dirs

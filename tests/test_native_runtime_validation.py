import json
from pathlib import PurePosixPath
import struct

import pytest

from scripts.validate_native_runtime import (
    OPENCV_FACE_CASCADE_NAME, REQUIRED_RESOURCE_SPECS, REQUIRED_ROOT_RESOURCE_NAMES,
    executable_architecture, validate_runtime,
)


def make_runtime(root, platform="linux", architecture="x64"):
    root.mkdir(exist_ok=True)
    executable = root / ("VantageBackend.exe" if platform == "win32" else "VantageBackend")
    data = bytearray(128)
    if platform == "win32":
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 60, 64)
        data[64:68] = b"PE\0\0"
        struct.pack_into("<H", data, 68, 0x8664 if architecture == "x64" else 0xAA64)
    elif platform == "darwin":
        data[:4] = b"\xcf\xfa\xed\xfe"
        struct.pack_into("<I", data, 4, 0x01000007 if architecture == "x64" else 0x0100000C)
    else:
        data[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", data, 18, 62 if architecture == "x64" else 183)
    executable.write_bytes(data)
    outputs = list(REQUIRED_ROOT_RESOURCE_NAMES)
    outputs.extend(str(PurePosixPath(destination) / PurePosixPath(source).name) for source, destination in REQUIRED_RESOURCE_SPECS)
    outputs.extend([f"opencv-data/{OPENCV_FACE_CASCADE_NAME}", "scienceplots/styles"])
    for item in outputs:
        path = root / "_internal" / item
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic resource")
    (root / "runtime-manifest.json").write_text(json.dumps({"runtime_name": "VantageBackend", "app_mode": "packaged", "resource_outputs": outputs}))
    (root / "runtime-fingerprint.json").write_text(json.dumps({"platform": {"sys_platform": platform, "machine": architecture}, "algorithm": "sha256", "digest": "a" * 64, "inputs": [{"path": "src/server.py"}]}))
    return executable


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
@pytest.mark.parametrize("architecture", ["x64", "arm64"])
def test_each_native_package_checks_actual_machine_type(tmp_path, platform, architecture):
    executable = make_runtime(tmp_path, platform, architecture)
    assert executable_architecture(executable, platform) == architecture
    assert validate_runtime(tmp_path, platform, architecture)["validated"] is True
    with pytest.raises(ValueError, match="architectures do not match"):
        validate_runtime(tmp_path, platform, "x64" if architecture == "arm64" else "arm64")


def test_missing_resource_cannot_be_packaged(tmp_path):
    make_runtime(tmp_path)
    (tmp_path / "_internal" / REQUIRED_ROOT_RESOURCE_NAMES[0]).unlink()
    with pytest.raises(ValueError, match="Missing bundled resource"):
        validate_runtime(tmp_path, "linux", "x64")


def test_manifest_cannot_hide_missing_resources(tmp_path):
    make_runtime(tmp_path)
    manifest = tmp_path / "runtime-manifest.json"
    value = json.loads(manifest.read_text())
    value["resource_outputs"] = ["../outside"]
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="inside the bundle"):
        validate_runtime(tmp_path, "linux", "x64")


def test_platform_fingerprint_cannot_disagree_with_executable(tmp_path):
    make_runtime(tmp_path)
    fingerprint = tmp_path / "runtime-fingerprint.json"
    value = json.loads(fingerprint.read_text())
    value["platform"]["sys_platform"] = "darwin"
    fingerprint.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="fingerprint"):
        validate_runtime(tmp_path, "linux", "x64")

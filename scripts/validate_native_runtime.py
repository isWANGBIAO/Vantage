"""Validate a prebuilt backend before embedding it in any native package.

This checks the shared manifest/resources, fingerprint platform and executable
architecture. It does not replace build_native_backend.py's launch smoke test.
No application is executed and no third-party Python packages are required.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import struct
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.backend_runtime_packaging import (
    OPENCV_FACE_CASCADE_NAME, REQUIRED_RESOURCE_SPECS, REQUIRED_ROOT_RESOURCE_NAMES,
    validate_backend_runtime_bundle,
)


def normalize_architecture(value: str) -> str:
    values = {"x64": "x64", "x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}
    try:
        return values[value.lower()]
    except (KeyError, AttributeError):
        raise ValueError("The native package target must be x64 or arm64.") from None


def executable_architecture(executable: Path, platform: str) -> str:
    with executable.open("rb") as handle:
        header = handle.read(64)
        if len(header) < 64:
            raise ValueError("The backend executable is truncated.")
        if platform == "win32":
            if header[:2] != b"MZ":
                raise ValueError("The Windows backend must be a PE executable.")
            handle.seek(struct.unpack_from("<I", header, 60)[0])
            pe = handle.read(6)
            if len(pe) != 6 or pe[:4] != b"PE\0\0":
                raise ValueError("The backend PE header is invalid.")
            machine = struct.unpack_from("<H", pe, 4)[0]
            architecture = {0x8664: "x64", 0xAA64: "arm64"}.get(machine)
        elif platform == "linux":
            if header[:4] != b"\x7fELF" or header[4] != 2 or header[5] not in (1, 2):
                raise ValueError("The Linux backend must be a 64-bit ELF executable.")
            machine = struct.unpack_from("<H" if header[5] == 1 else ">H", header, 18)[0]
            architecture = {62: "x64", 183: "arm64"}.get(machine)
        elif platform == "darwin":
            if header[:4] not in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"):
                raise ValueError("Build a separate 64-bit Mach-O backend for each macOS target architecture.")
            machine = struct.unpack_from("<I" if header[:4] == b"\xcf\xfa\xed\xfe" else ">I", header, 4)[0]
            architecture = {0x01000007: "x64", 0x0100000C: "arm64"}.get(machine)
        else:
            raise ValueError("Unsupported native target platform.")
    if architecture is None:
        raise ValueError("The backend executable architecture is unsupported.")
    return architecture


def validate_runtime(runtime: str | Path, platform: str, architecture: str) -> dict:
    runtime = Path(runtime).resolve(strict=True)
    arch = normalize_architecture(architecture)
    executable = runtime / ("VantageBackend.exe" if platform == "win32" else "VantageBackend")
    if executable_architecture(executable, platform) != arch:
        raise ValueError("The backend executable and native client architectures do not match.")
    manifest = json.loads((runtime / "runtime-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("runtime_name") != "VantageBackend" or manifest.get("app_mode") != "packaged":
        raise ValueError("The backend runtime manifest is invalid.")
    outputs = manifest.get("resource_outputs")
    if not isinstance(outputs, list) or not outputs:
        raise ValueError("The runtime manifest has no resource inventory.")
    for name in outputs:
        if not isinstance(name, str) or "\\" in name:
            raise ValueError("Invalid resource path in backend manifest.")
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or ":" in name:
            raise ValueError("Backend manifest resources must stay inside the bundle.")
        if not (runtime / "_internal" / name).resolve().is_relative_to(runtime):
            raise ValueError("Backend resource symlink escapes the bundle.")
    required = set(REQUIRED_ROOT_RESOURCE_NAMES)
    required.update(str(PurePosixPath(destination) / PurePosixPath(source).name) for source, destination in REQUIRED_RESOURCE_SPECS)
    required.update({f"opencv-data/{OPENCV_FACE_CASCADE_NAME}", "scienceplots/styles"})
    missing = required - set(outputs)
    if missing:
        raise ValueError("Backend manifest omitted required resources: " + ", ".join(sorted(missing)))
    layout = {
        "executable_path": executable, "manifest_path": runtime / "runtime-manifest.json",
        "runtime_dir": runtime, "resource_dir": runtime / "_internal",
    }
    resources = [SimpleNamespace(output_relative_path=Path(name)) for name in outputs]
    errors = validate_backend_runtime_bundle(layout, resources)
    if errors:
        raise ValueError("; ".join(errors))
    fingerprint = json.loads((runtime / "runtime-fingerprint.json").read_text(encoding="utf-8"))
    identity = fingerprint.get("platform", {})
    if identity.get("sys_platform") != platform or normalize_architecture(identity.get("machine", "")) != arch:
        raise ValueError("Backend fingerprint does not match the native target.")
    if fingerprint.get("algorithm") != "sha256" or len(fingerprint.get("digest", "")) != 64 or not fingerprint.get("inputs"):
        raise ValueError("Backend fingerprint is missing its validated build inputs.")
    return {"validated": True, "platform": platform, "architecture": arch, "resources": len(outputs)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--platform", required=True, choices=["win32", "darwin", "linux"])
    parser.add_argument("--architecture", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(validate_runtime(args.runtime, args.platform, args.architecture)))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

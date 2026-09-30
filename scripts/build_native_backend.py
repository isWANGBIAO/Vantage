"""Build and launch-verify the shared backend used by native desktop packages.

This deliberately uses the same isolated, fingerprinted packaging environment
and verifier as the Electron release. Native clients do not carry a second
backend implementation or install dependencies on the user's first launch.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def build_commands(root: Path, platform: str, python: str, timeout: int) -> list[list[str]]:
    venv = root / ".venv-backend-runtime-gpu"
    backend_python = venv / ("Scripts/python.exe" if platform == "win32" else "bin/python")
    scripts = root / "src/scripts"
    commands = [
        [python, str(scripts / "sync_backend_runtime_environment.py"),
         "--project-root", str(root), "--venv", str(venv),
         "--core-requirements", str(root / "requirements-core.txt"),
         "--requirements", str(root / "requirements-backend-runtime-gpu.txt"),
         "--opencv-normalizer", str(scripts / "normalize_opencv_installation.py")],
        [str(backend_python), "-m", "pip", "check"],
    ]
    if platform == "darwin":
        # Ad-hoc signatures only. This neither accesses a signing identity nor
        # publishes/notarizes a release. The packager validates this stamp.
        commands.append([
            python, str(scripts / "sign_macos_backend_runtime.py"),
            "--project-root", str(root), "--venv", str(venv),
            "--state", str(venv / ".vantage-backend-runtime-state.json"),
            "--stamp", str(venv / ".macos-native-codesign.sha256"),
        ])
    commands.extend([
        [str(backend_python), str(scripts / "build_backend_runtime.py"), "--reuse-if-unchanged"],
        [str(backend_python), str(scripts / "verify_backend_runtime.py"),
         "--timeout-seconds", str(timeout), "--isolated"],
    ])
    return commands


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    args = parser.parse_args(argv)
    if not 1 <= args.timeout_seconds <= 600:
        parser.error("--timeout-seconds must be between 1 and 600")
    for command in build_commands(ROOT, sys.platform, sys.executable, args.timeout_seconds):
        print(f"Native backend: {Path(command[1]).name if len(command) > 1 else command[0]}", flush=True)
        subprocess.run(command, cwd=ROOT, check=True)
    print("Shared backend built and launch-verified.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

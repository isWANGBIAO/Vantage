from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


def build_locked_backend_command(
    *,
    project_root: str | Path,
    lock_runner: str | Path,
    backend_python: str | Path,
    bootstrap_python: str | Path,
) -> list[str]:
    return [
        str(bootstrap_python),
        str(lock_runner),
        "--project-root",
        str(project_root),
        "--",
        str(backend_python),
        "src/scripts/run_server_background.py",
    ]


def _creationflags(platform_name: str) -> int:
    if platform_name != "nt":
        return 0
    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        flags |= int(getattr(subprocess, name, 0))
    return flags


def launch_locked_backend_background(
    *,
    project_root: str | Path,
    lock_runner: str | Path,
    backend_python: str | Path,
    bootstrap_python: str | Path = sys.executable,
    popen=subprocess.Popen,
    platform_name: str = os.name,
):
    resolved_root = Path(project_root).resolve()
    command = build_locked_backend_command(
        project_root=resolved_root,
        lock_runner=Path(lock_runner).resolve(),
        backend_python=Path(backend_python).resolve(),
        bootstrap_python=bootstrap_python,
    )
    environment = os.environ.copy()
    environment.pop("VANTAGE_BACKEND_RUNTIME_LOCK_HELD", None)
    return popen(
        command,
        cwd=str(resolved_root),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=_creationflags(platform_name),
        start_new_session=platform_name != "nt",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch the source backend under its runtime lifecycle supervisor.",
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--lock-runner", required=True, type=Path)
    parser.add_argument("--backend-python", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        process = launch_locked_backend_background(
            project_root=args.project_root,
            lock_runner=args.lock_runner,
            backend_python=args.backend_python,
        )
    except OSError as exc:
        print(f"Locked backend launch failed: {exc}", file=sys.stderr)
        return 1
    print(f"Locked backend launch requested: pid={process.pid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

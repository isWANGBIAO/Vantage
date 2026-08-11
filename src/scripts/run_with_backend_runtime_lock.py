from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


def _ensure_project_root_on_sys_path(script_path: str | Path | None = None) -> Path:
    current_script = Path(script_path or __file__).resolve()
    project_root = current_script.parents[2]
    project_root_text = str(project_root)
    if project_root_text not in sys.path:
        sys.path.insert(0, project_root_text)
    return project_root


_ensure_project_root_on_sys_path()

from src.core.backend_runtime_lock import (
    DEFAULT_BACKEND_RUNTIME_LOCK_TIMEOUT_SECONDS,
    backend_runtime_lock,
    inherited_backend_runtime_lock_environment,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one backend-runtime consumer while holding its lifecycle lock.",
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_BACKEND_RUNTIME_LOCK_TIMEOUT_SECONDS,
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        print("Backend runtime lock supervisor requires a command.", file=sys.stderr)
        return 2

    try:
        with backend_runtime_lock(
            args.project_root,
            timeout_seconds=args.timeout_seconds,
        ):
            environment = inherited_backend_runtime_lock_environment(args.project_root)
            process = subprocess.Popen(command, env=environment)
            return process.wait()
    except (OSError, TimeoutError, ValueError) as exc:
        print(f"Backend runtime lock supervisor failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

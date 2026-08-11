from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
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

from src.core.backend_runtime_lock import backend_runtime_lock
from src.utils.subprocess_safety import BoundedTextEmitter, run_bounded_subprocess


PACKAGING_SUBPROCESS_TIMEOUT_SECONDS = 60 * 60
PACKAGING_SUBPROCESS_OUTPUT_LIMIT_BYTES = 256 * 1024


def _configure_console_encoding():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run independent packaging build steps in parallel.",
    )
    parser.add_argument(
        "--backend-python",
        default=sys.executable,
        help="Python executable from the clean backend runtime packaging environment.",
    )
    parser.add_argument(
        "--project-root",
        default=str(PROJECT_ROOT),
        help="Repository root. Defaults to the root containing this script.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Requested parallel build workers. Capped by the number of independent build tasks.",
    )
    return parser


def _resolve_npm_command() -> str:
    npm_command = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm_command:
        raise RuntimeError("npm was not found on PATH.")
    return npm_command


def build_packaging_commands(
    project_root: str | Path,
    *,
    backend_python: str | Path,
    npm_command: str | None = None,
) -> dict[str, dict[str, object]]:
    resolved_root = Path(project_root).resolve()
    resolved_npm = npm_command or _resolve_npm_command()
    return {
        "backend": {
            "command": [
                str(backend_python),
                "src/scripts/build_backend_runtime.py",
                "--reuse-if-unchanged",
            ],
            "cwd": resolved_root,
        },
        "frontend": {
            "command": [
                resolved_npm,
                "run",
                "build",
            ],
            "cwd": resolved_root / "src" / "webapp",
        },
    }


def _run_command(
    name: str,
    command: list[str],
    cwd: Path,
    *,
    timeout_seconds: float = PACKAGING_SUBPROCESS_TIMEOUT_SECONDS,
    output_limit_bytes: int = PACKAGING_SUBPROCESS_OUTPUT_LIMIT_BYTES,
) -> int:
    emitter = BoundedTextEmitter(
        limit_bytes=output_limit_bytes,
        path_prefixes={
            "<PROJECT_ROOT>": cwd,
            "<USER_HOME>": Path.home(),
        },
    )

    def emit(value: str) -> None:
        filtered = emitter.filter(value)
        if filtered:
            print(filtered, end="", flush=True)

    emit(f"[{name}] starting: {' '.join(command)}\n")
    try:
        result = run_bounded_subprocess(
            command,
            timeout_seconds=timeout_seconds,
            output_limit_bytes=output_limit_bytes,
            cwd=str(cwd),
        )
    except subprocess.TimeoutExpired as exc:
        for captured in (exc.output, exc.stderr):
            if captured:
                if isinstance(captured, bytes):
                    captured = captured.decode("utf-8", errors="replace")
                emit(f"[{name}] {captured}")
        emit(f"[{name}] timed out after {timeout_seconds:g} seconds\n")
        return 124
    for captured in (result.stdout, result.stderr):
        if captured:
            emit(f"[{name}] {captured}")
    emit(f"[{name}] exited with {result.returncode}\n")
    return result.returncode


def resolve_build_worker_count(
    requested_workers: int | None,
    *,
    command_count: int,
    cpu_count: int | None = None,
) -> int:
    available_commands = max(1, command_count)
    if requested_workers is None or requested_workers <= 0:
        requested_workers = cpu_count if cpu_count is not None else os.cpu_count()
    if requested_workers is None or requested_workers <= 0:
        requested_workers = 1
    return max(1, min(requested_workers, available_commands))


def run_packaging_builds(
    commands: dict[str, dict[str, object]],
    *,
    workers: int | None = None,
) -> int:
    failures: list[str] = []
    worker_count = resolve_build_worker_count(workers, command_count=len(commands))
    print(
        f"Packaging build workers: {worker_count} active for "
        f"{len(commands)} independent tasks",
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(
                _run_command,
                name,
                list(spec["command"]),
                Path(spec["cwd"]),
            ): name
            for name, spec in commands.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            return_code = future.result()
            if return_code != 0:
                failures.append(f"{name}={return_code}")

    if failures:
        print("Packaging build step failed: " + ", ".join(failures), file=sys.stderr)
        return 1
    return 0


def _main_without_backend_runtime_lock() -> int:
    _configure_console_encoding()
    parser = _build_parser()
    args = parser.parse_args()
    commands = build_packaging_commands(
        args.project_root,
        backend_python=args.backend_python,
    )
    return run_packaging_builds(commands, workers=args.workers)


def main() -> int:
    with backend_runtime_lock(PROJECT_ROOT, mode="shared"):
        return _main_without_backend_runtime_lock()


if __name__ == "__main__":
    raise SystemExit(main())

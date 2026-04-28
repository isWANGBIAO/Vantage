from __future__ import annotations

import argparse
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


def _run_command(name: str, command: list[str], cwd: Path) -> int:
    print(f"[{name}] starting: {' '.join(command)}", flush=True)
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(f"[{name}] {line}", end="", flush=True)
    return_code = process.wait()
    print(f"[{name}] exited with {return_code}", flush=True)
    return return_code


def run_packaging_builds(commands: dict[str, dict[str, object]]) -> int:
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=len(commands)) as executor:
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


def main() -> int:
    _configure_console_encoding()
    parser = _build_parser()
    args = parser.parse_args()
    commands = build_packaging_commands(
        args.project_root,
        backend_python=args.backend_python,
    )
    return run_packaging_builds(commands)


if __name__ == "__main__":
    raise SystemExit(main())

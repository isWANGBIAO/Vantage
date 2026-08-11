from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import subprocess
import sys


def _ensure_project_root_on_sys_path() -> None:
    project_root = str(Path(__file__).resolve().parents[2])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


_ensure_project_root_on_sys_path()

from src.utils.subprocess_safety import (
    BoundedTextEmitter,
    DEFAULT_SUBPROCESS_OUTPUT_LIMIT_BYTES,
    DEFAULT_SUBPROCESS_TIMEOUT_SECONDS,
    run_bounded_subprocess,
)


def run_bounded_command(
    command: Sequence[str],
    *,
    timeout_seconds: float = DEFAULT_SUBPROCESS_TIMEOUT_SECONDS,
    output_limit_bytes: int = DEFAULT_SUBPROCESS_OUTPUT_LIMIT_BYTES,
    cwd: os.PathLike[str] | str | None = None,
    env: Mapping[str, str] | None = None,
    path_prefixes: Mapping[str, object] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command with bounded output and ownership of its process tree."""
    if not command:
        raise ValueError("a command is required")
    return run_bounded_subprocess(
        command,
        timeout_seconds=timeout_seconds,
        output_limit_bytes=output_limit_bytes,
        cwd=cwd,
        env=env,
        path_prefixes=path_prefixes,
    )


def _bounded_redacted_text(
    value: object,
    *,
    output_limit_bytes: int,
    path_prefixes: Mapping[str, object],
) -> str:
    emitter = BoundedTextEmitter(
        limit_bytes=output_limit_bytes,
        path_prefixes=path_prefixes,
    )
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    elif value is None:
        text = ""
    else:
        text = str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return emitter.filter(text)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one build command with bounded, redacted output.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_SUBPROCESS_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--output-limit-bytes",
        type=int,
        default=DEFAULT_SUBPROCESS_OUTPUT_LIMIT_BYTES,
    )
    parser.add_argument(
        "--redact-path",
        nargs=2,
        action="append",
        default=[],
        metavar=("LABEL", "PATH"),
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command must follow --")

    path_prefixes = {str(label): path for label, path in args.redact_path}
    try:
        result = run_bounded_command(
            command,
            timeout_seconds=args.timeout_seconds,
            output_limit_bytes=args.output_limit_bytes,
            path_prefixes=path_prefixes,
        )
    except subprocess.TimeoutExpired as exc:
        detail = _bounded_redacted_text(
            exc.stderr or exc.output,
            output_limit_bytes=args.output_limit_bytes,
            path_prefixes=path_prefixes,
        ).strip()
        suffix = f": {detail}" if detail else ""
        sys.stderr.write(f"command timed out after the configured limit{suffix}\n")
        return 1
    except (OSError, RuntimeError, ValueError) as exc:
        detail = _bounded_redacted_text(
            exc,
            output_limit_bytes=args.output_limit_bytes,
            path_prefixes=path_prefixes,
        ).strip()
        sys.stderr.write(f"command could not be started: {detail}\n")
        return 1

    if result.returncode != 0:
        detail = _bounded_redacted_text(
            result.stderr or result.stdout,
            output_limit_bytes=args.output_limit_bytes,
            path_prefixes=path_prefixes,
        ).strip()
        suffix = f": {detail}" if detail else ""
        sys.stderr.write(f"command failed with exit code {result.returncode}{suffix}\n")
        return 1

    output = _bounded_redacted_text(
        result.stdout,
        output_limit_bytes=args.output_limit_bytes,
        path_prefixes=path_prefixes,
    )
    if output:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

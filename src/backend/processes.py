"""Packaged/development subprocess entry points and working directories."""

import asyncio
import os
import sys
from pathlib import Path

from src.core.config import Config

from . import source_paths as _source_paths

RUN_PROMPT_BRIDGE_ARG = "--run-prompt"
RUN_FACE_ANALYSIS_BRIDGE_ARG = "--run-face-analysis"

def _get_runtime_workdir():
    return Path(Config.get_project_root())

def _is_frozen_runtime():
    return bool(getattr(sys, "frozen", False))

def _resolve_run_prompt_script_path():
    current_dir = os.path.dirname(os.path.abspath(_source_paths.SERVER_FILE))
    script_path = os.path.join(current_dir, "scripts", "run_prompt.py")
    if not os.path.exists(script_path):
        script_path = os.path.abspath("src/scripts/run_prompt.py")
    return script_path

def _build_run_prompt_subprocess(run_prompt_args=None):
    resolved_args = list(run_prompt_args or [])
    if _is_frozen_runtime():
        return [sys.executable, RUN_PROMPT_BRIDGE_ARG, *resolved_args], str(_get_runtime_workdir())

    script_path = _resolve_run_prompt_script_path()
    return [sys.executable, script_path, *resolved_args], os.path.dirname(script_path)


def _build_face_analysis_subprocess(arguments=None):
    """A frozen executable must dispatch a mode, never receive a Python file."""
    arguments = list(arguments or [])
    if _is_frozen_runtime():
        return [sys.executable, RUN_FACE_ANALYSIS_BRIDGE_ARG, *arguments], str(_get_runtime_workdir())
    script = Path(_source_paths.SERVER_FILE).resolve().parent / "scripts" / "analyze_face.py"
    return [sys.executable, str(script), *arguments], str(_get_runtime_workdir())


def terminate_subprocess(process):
    """Request termination without turning an exit race into a failed job."""
    if process is not None and process.returncode is None:
        try:
            process.terminate()
        except ProcessLookupError:
            # The OS can report exit before asyncio's child watcher updates
            # returncode. The caller still reaps the child in its finally block.
            pass


async def reap_subprocess(process):
    """Kill the child and drain owned pipes so wait cannot stall on backpressure."""
    if process is None:
        return
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    async def discard_output(stream):
        read = getattr(stream, "read", None)
        if callable(read):
            while await read(64 * 1024):
                pass

    # StreamReader pauses its transport when output exceeds the buffer limit.
    # Process.wait may then wait for pipe closure even after the child exited.
    # Discard in bounded chunks, not communicate(), which retains all output.
    await asyncio.gather(
        discard_output(getattr(process, "stdout", None)),
        discard_output(getattr(process, "stderr", None)),
        process.wait(),
    )

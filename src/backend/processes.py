"""Packaged/development subprocess entry points and working directories."""

import os
import sys
from pathlib import Path

from src.core.config import Config

from . import source_paths as _source_paths

RUN_PROMPT_BRIDGE_ARG = "--run-prompt"

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
    """Kill any remaining child and always wait for its exit to be collected."""
    if process is None:
        return
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.wait()

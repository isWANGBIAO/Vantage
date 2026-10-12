"""Probe and explicitly install an isolated local SAM3 runtime.

The frozen Vantage backend never imports its optional ML packages.  This module
only starts a separate CPython process and never reads source photographs.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Iterable

from src.core.user_config import get_body_analysis_report_root


# These are optional direct dependencies, not part of the PyInstaller backend.
# The CUDA 13.0 wheel is appropriate for this machine's existing PyTorch setup.
# A different CUDA runtime requires an explicit future compatibility decision.
TORCH_VERSION = "2.9.0"
PYTORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu130"
OPTIONAL_PACKAGE_SPECS = (
    "transformers==5.3.0",
    "numpy==2.2.6",
    "Pillow==11.3.0",
    "opencv-python-headless==4.12.0.88",
    "scikit-image==0.25.2",
)
_PYTHON_IDENTITY_CODE = (
    "import json,sys; print(json.dumps({'implementation':sys.implementation.name,"
    "'version':list(sys.version_info[:2]),'executable':sys.executable}))"
)
_CAPABILITY_CODE = (
    "import json; import cv2,numpy,PIL,skimage,torch; "
    "from transformers import Sam3Model,Sam3Processor; "
    "print(json.dumps({'ready':True,'cuda':bool(torch.cuda.is_available())}))"
)


def get_body_analysis_environment_root() -> Path:
    """Use validated user history, never the repository's default dev data dir."""
    return get_body_analysis_report_root() / "sam3-environment"


def get_environment_python_path(env_root: str | Path) -> Path:
    root = Path(env_root).expanduser().resolve()
    return root / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _status(
    state: str,
    *,
    missing: Iterable[str] = (),
    python_executable: Path | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    return {
        "state": state,
        "ready": state in {"ready", "installed"},
        "reason": reason or state,
        "missing": list(missing),
        "python_executable": str(python_executable) if python_executable else None,
    }


def _checkpoint_exists(model_dir: str | Path | None) -> bool:
    if not model_dir:
        return False
    model = Path(model_dir).expanduser()
    if not model.is_dir() or not (model / "config.json").is_file():
        return False
    return any(
        (model / name).is_file()
        for name in ("model.safetensors", "model.safetensors.index.json", "pytorch_model.bin")
    )


def _identity_for_candidate(
    command: list[str], run_command: Callable[..., object]
) -> Path | None:
    try:
        result = run_command(
            [*command, "-c", _PYTHON_IDENTITY_CODE],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if result.returncode != 0:
            return None
        identity = json.loads(result.stdout)
        if identity.get("implementation") != "cpython":
            return None
        if identity.get("version") != [3, 11]:
            return None
        executable = Path(identity["executable"]).expanduser().resolve()
        return executable if executable.is_file() else None
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        return None


def discover_body_analysis_python(
    *,
    python_candidates: Iterable[str | Path] | None = None,
    run_command: Callable[..., object] | None = None,
) -> Path | None:
    """Find a real CPython 3.11; a frozen backend is never a creator."""
    runner = run_command or subprocess.run
    if python_candidates is not None:
        candidates = [[str(Path(candidate).expanduser())] for candidate in python_candidates]
    else:
        candidates = []
        if not getattr(sys, "frozen", False):
            candidates.append([sys.executable])
        if sys.platform == "win32":
            launcher = shutil.which("py")
            if launcher:
                candidates.append([launcher, "-3.11"])
        for name in ("python3.11", "python3", "python"):
            executable = shutil.which(name)
            if executable and not any(candidate[0] == executable for candidate in candidates):
                candidates.append([executable])
    for candidate in candidates:
        python = _identity_for_candidate(candidate, runner)
        if python is not None:
            return python
    return None


def probe_body_analysis_environment(
    model_dir: str | Path | None,
    *,
    env_root: str | Path | None = None,
    python_candidates: Iterable[str | Path] | None = None,
    run_command: Callable[..., object] | None = None,
) -> dict[str, object]:
    """Check files, optional interpreter imports and CUDA; never load weights."""
    if not _checkpoint_exists(model_dir):
        return _status("missing_model", missing=("model",))
    root = Path(env_root).expanduser().resolve() if env_root is not None else get_body_analysis_environment_root()
    python = get_environment_python_path(root)
    runner = run_command or subprocess.run
    if not python.is_file():
        if discover_body_analysis_python(python_candidates=python_candidates, run_command=runner) is None:
            return _status("missing_python", missing=("python",))
        return _status("missing_dependencies", missing=("dependencies",))
    try:
        result = runner(
            [str(python), "-c", _CAPABILITY_CODE],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return _status("missing_dependencies", missing=("dependencies",))
        capability = json.loads(result.stdout)
        if capability.get("ready") is not True:
            return _status("missing_dependencies", missing=("dependencies",))
        if capability.get("cuda") is not True:
            return _status("unsupported", missing=("cuda",), reason="cuda_unavailable")
        return _status("ready", python_executable=python)
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        return _status("missing_dependencies", missing=("dependencies",))


def _run_install_step(
    command: list[str],
    *,
    popen_factory: Callable[..., object],
    cancel_event: threading.Event,
) -> str:
    try:
        process = popen_factory(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        while process.poll() is None:
            if cancel_event.wait(0.1):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                return "cancelled"
        return "completed" if process.returncode == 0 else "failed"
    except (OSError, subprocess.TimeoutExpired):
        return "failed"


def install_body_analysis_environment(
    model_dir: str | Path | None,
    *,
    explicit: bool = False,
    env_root: str | Path | None = None,
    python_candidates: Iterable[str | Path] | None = None,
    run_command: Callable[..., object] | None = None,
    popen_factory: Callable[..., object] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, object]:
    """Install pinned wheels only after a user action, into a dedicated venv."""
    if not explicit:
        return _status("permission_required")
    cancellation = cancel_event or threading.Event()
    if cancellation.is_set():
        return _status("cancelled")
    if not _checkpoint_exists(model_dir):
        return _status("missing_model", missing=("model",))
    if sys.platform != "win32":
        return _status("unsupported", reason="cuda_wheel_platform_unsupported")
    runner = run_command or subprocess.run
    creator = discover_body_analysis_python(python_candidates=python_candidates, run_command=runner)
    if creator is None:
        return _status("missing_python", missing=("python",))
    root = Path(env_root).expanduser().resolve() if env_root is not None else get_body_analysis_environment_root()
    python = get_environment_python_path(root)
    launch = popen_factory or subprocess.Popen
    if not python.is_file():
        result = _run_install_step(
            [str(creator), "-m", "venv", str(root)],
            popen_factory=launch,
            cancel_event=cancellation,
        )
        if result != "completed":
            return _status("cancelled" if result == "cancelled" else "failed", reason="venv_creation_" + result)
        if not python.is_file():
            return _status("failed", reason="venv_creation_failed")
    steps = (
        [str(python), "-m", "pip", "install", "--only-binary=:all:",
         "--index-url", PYTORCH_CUDA_INDEX, f"torch=={TORCH_VERSION}"],
        [str(python), "-m", "pip", "install", "--only-binary=:all:", *OPTIONAL_PACKAGE_SPECS],
    )
    for command in steps:
        if cancellation.is_set():
            return _status("cancelled")
        result = _run_install_step(command, popen_factory=launch, cancel_event=cancellation)
        if result != "completed":
            return _status("cancelled" if result == "cancelled" else "failed", reason="package_install_" + result)
    checked = probe_body_analysis_environment(
        model_dir, env_root=root, python_candidates=python_candidates, run_command=runner
    )
    if checked["ready"]:
        return _status("installed", python_executable=python)
    return _status("failed", missing=checked["missing"], reason="post_install_probe_failed")

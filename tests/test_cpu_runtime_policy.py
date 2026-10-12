"""Verify startup policy without importing native libraries or using a GPU."""

import ast
import importlib
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest


ROOT = Path(__file__).resolve().parents[1]
POLICY_MODULE = "src.core.cpu_runtime_policy"
RUNTIME_ENV = "OPENCV_OPENCL_RUNTIME"


def _startup_prefix(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    prefix = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            modules = []
        if any(
            module != POLICY_MODULE and module.split(".")[0] not in sys.stdlib_module_names
            for module in modules
        ):
            break
        prefix.append(node)
    return ast.Module(body=prefix, type_ignores=[])


def _policy():
    assert (ROOT / "src/core/cpu_runtime_policy.py").is_file(), "CPU runtime policy is missing"
    return importlib.import_module(POLICY_MODULE).configure_cpu_runtime


@pytest.mark.parametrize("inherited", [None, "", "enabled", "OpenCL.dll", "disabled"])
def test_policy_forces_process_local_opencl_disable(monkeypatch, inherited):
    if inherited is None:
        monkeypatch.delenv(RUNTIME_ENV, raising=False)
    else:
        monkeypatch.setenv(RUNTIME_ENV, inherited)
    _policy()()
    _policy()()
    assert os.environ[RUNTIME_ENV] == "disabled"


def test_policy_is_visible_to_workers_without_thread_local_cv2_toggle(monkeypatch):
    monkeypatch.setenv(RUNTIME_ENV, "enabled")
    with ThreadPoolExecutor(max_workers=1) as worker:
        worker.submit(_policy()).result()
        assert worker.submit(lambda: os.environ[RUNTIME_ENV]).result() == "disabled"
    assert os.environ[RUNTIME_ENV] == "disabled"


def test_child_process_inherits_disabled_runtime(monkeypatch):
    monkeypatch.setenv(RUNTIME_ENV, "enabled")
    _policy()()
    child = subprocess.run(
        [sys.executable, "-c", "import os; print(os.environ['OPENCV_OPENCL_RUNTIME'])"],
        capture_output=True, text=True, check=True, timeout=15,
    )
    assert child.stdout.strip() == "disabled"


@pytest.mark.parametrize("relative_path", [
    "src/server.py",
    "src/cli.py",
    "src/mcp_server.py",
    "src/scripts/run_server_background.py",
    "src/scripts/pyinstaller_runtime_hook.py",
    "src/scripts/analyze_face.py",
    "src/services/face_analysis_pipeline.py",
    "src/services/person_detection.py",
    "src/backend/camera.py",
    "src/manager/get_location.py",
    "src/manager/take_photo/take_a_photo.py",
    "src/manager/take_photo/get_best_photo.py",
    "src/manager/screenshot/take_a_screenshot.py",
])
def test_policy_precedes_application_or_native_imports(monkeypatch, relative_path):
    # Execute the real startup prefix only; stop before any native dependency,
    # framework, or product module. This cannot open a camera or start a server.
    monkeypatch.setenv(RUNTIME_ENV, "enabled")
    path = ROOT / relative_path
    namespace = {"__file__": str(path), "__name__": "startup_policy_test", "__package__": None}
    exec(compile(_startup_prefix(path), str(path), "exec"), namespace)
    assert os.environ[RUNTIME_ENV] == "disabled", f"{relative_path} imports dependencies before policy"


@pytest.mark.parametrize("relative_path", [
    "src/server.py",
    "src/scripts/run_server_background.py",
    "src/scripts/analyze_face.py",
    "src/manager/take_photo/get_best_photo.py",
])
def test_direct_script_bootstrap_outside_repository(monkeypatch, tmp_path, relative_path):
    monkeypatch.setenv(RUNTIME_ENV, "enabled")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    path = ROOT / relative_path
    source = ast.unparse(_startup_prefix(path))
    # Match direct script startup: the script directory, not repo root, is first.
    script = (
        f"import sys; sys.path[0] = {str(path.parent)!r}\n"
        f"__file__ = {str(path)!r}\n__name__ = 'startup_policy_test'\n__package__ = None\n"
        + source + "\nimport os; print(os.environ['OPENCV_OPENCL_RUNTIME'])"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path,
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "disabled"

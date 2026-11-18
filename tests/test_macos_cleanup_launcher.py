import os
import shlex
import subprocess
import sys
from pathlib import Path
import time

import pytest


def _bash_function(launcher_path: Path, function_name: str) -> str:
    launcher = launcher_path.read_text(encoding="utf-8")
    start = launcher.index(f"{function_name}() {{")
    end = launcher.index("\n}\n", start) + len("\n}\n")
    return launcher[start:end]


def _synthetic_python(path: Path, version: tuple[int, int]) -> Path:
    code = f"import sys; sys.version_info = {version!r}; exec(sys.argv[1])"
    path.write_text(
        f'#!/bin/bash\nexec {shlex.quote(sys.executable)} -c {shlex.quote(code)} "$2"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def test_macos_cleanup_prefers_existing_runtime_python_under_lifecycle_lock_before_sync():
    for launcher_path in (Path("RUN.sh"), Path("RUN_DEV.sh")):
        launcher = launcher_path.read_text(encoding="utf-8")
        selector_index = launcher.index(
            'BACKEND_CLEANUP_PYTHON="$(select_backend_cleanup_python)"'
        )
        cleanup_index = launcher.index("cleanup_vantage_python_processes.py")
        sync_index = launcher.index('"$BOOTSTRAP_PYTHON" "$BACKEND_RUNTIME_SYNC"')

        assert "select_backend_cleanup_python" in launcher
        assert '[[ -x "$BACKEND_RUNTIME_PYTHON" ]]' in launcher
        assert 'python_supports_backend_venv "$BACKEND_RUNTIME_PYTHON"' in launcher
        assert '"$BACKEND_CLEANUP_PYTHON"' in launcher
        assert selector_index < cleanup_index < sync_index
        assert '"$BOOTSTRAP_PYTHON" "$BACKEND_RUNTIME_LOCK_RUNNER"' in launcher[
            cleanup_index - 180 : cleanup_index + 180
        ]


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX shell process semantics")
def test_macos_cleanup_python_selector_falls_back_for_old_or_unusable_runtime(tmp_path):
    runtime = _synthetic_python(tmp_path / "runtime-python", (3, 11))
    old_runtime = _synthetic_python(tmp_path / "old-runtime-python", (3, 13))
    bootstrap = _synthetic_python(tmp_path / "bootstrap-python", (3, 11))
    for launcher_path in (Path("RUN.sh"), Path("RUN_DEV.sh")):
        selector = _bash_function(launcher_path, "select_backend_cleanup_python")
        probe = _bash_function(launcher_path, "python_supports_backend_venv")
        harness = f"""
set -eu
BOOTSTRAP_PYTHON={shlex.quote(str(bootstrap))}
BACKEND_RUNTIME_PYTHON={shlex.quote(str(runtime))}
{probe}
{selector}
select_backend_cleanup_python
BACKEND_RUNTIME_PYTHON={shlex.quote(str(old_runtime))}
select_backend_cleanup_python
BACKEND_RUNTIME_PYTHON={shlex.quote(str(tmp_path / 'missing'))}
select_backend_cleanup_python
"""
        result = subprocess.run(
            ["bash", "-s"],
            input=harness.encode("utf-8"),
            capture_output=True,
            check=False,
            timeout=8,
        )

        stderr = result.stderr.decode("utf-8", errors="replace")
        stdout = result.stdout.decode("utf-8", errors="replace")
        assert result.returncode == 0, stderr
        assert [Path(line).name for line in stdout.splitlines()] == [
            "runtime-python",
            "bootstrap-python",
            "bootstrap-python",
        ]


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX shell process semantics")
def test_bootstrap_probe_rejects_and_terminates_early_parent_descendant(tmp_path):
    sentinel = tmp_path / "descendant-survived.txt"
    candidate = tmp_path / "early-parent-python"
    candidate.write_text(
        "#!/bin/bash\n"
        f"( sleep 1; printf survived > '{sentinel.as_posix()}' ) &\n"
        "exit 0\n",
        encoding="utf-8",
    )
    candidate.chmod(0o755)

    for launcher_path in (Path("RUN.sh"), Path("RUN_DEV.sh")):
        sentinel.unlink(missing_ok=True)
        function_source = _bash_function(
            launcher_path,
            "python_supports_backend_venv",
        )
        harness = f"""
set -eu
{function_source}
if python_supports_backend_venv '{candidate.as_posix()}'; then
    exit 9
fi
"""
        started = time.monotonic()
        result = subprocess.run(
            ["bash", "-s"],
            input=harness.encode("utf-8"),
            capture_output=True,
            check=False,
            timeout=8,
        )
        elapsed = time.monotonic() - started

        assert result.returncode == 0, result.stderr.decode(
            "utf-8", errors="replace"
        )
        assert elapsed < 3
        time.sleep(1.2)
        assert not sentinel.exists()


def test_bootstrap_probe_uses_no_unbounded_output_file_and_owns_process_group():
    for launcher_path in (Path("RUN.sh"), Path("RUN_DEV.sh")):
        function_source = _bash_function(
            launcher_path,
            "python_supports_backend_venv",
        )

        assert "probe_file" not in function_source
        assert "set -m" in function_source
        assert 'kill -TERM -- "-$probe_pid"' in function_source
        assert 'kill -KILL -- "-$probe_pid"' in function_source
        assert ">/dev/null 2>&1" in function_source


def test_macos_bootstrap_has_a_single_supported_python_minor():
    for launcher_path in (Path("RUN.sh"), Path("RUN_DEV.sh")):
        resolver = _bash_function(launcher_path, "resolve_bootstrap_python")
        probe = _bash_function(launcher_path, "python_supports_backend_venv")
        assert '(3, 11)' in probe
        assert 'command -v python3.11' in resolver
        assert 'Python 3.11 with venv support' in resolver
        assert 'python3.13' not in launcher_path.read_text(encoding="utf-8")

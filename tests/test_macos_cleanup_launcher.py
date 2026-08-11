import subprocess
from pathlib import Path
import time


def _bash_function(launcher_path: Path, function_name: str) -> str:
    launcher = launcher_path.read_text(encoding="utf-8")
    start = launcher.index(f"{function_name}() {{")
    end = launcher.index("\n}\n", start) + len("\n}\n")
    return launcher[start:end]


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
        assert '"$BACKEND_CLEANUP_PYTHON"' in launcher
        assert selector_index < cleanup_index < sync_index
        assert '"$BOOTSTRAP_PYTHON" "$BACKEND_RUNTIME_LOCK_RUNNER"' in launcher[
            cleanup_index - 180 : cleanup_index + 180
        ]


def test_macos_cleanup_python_selector_falls_back_only_when_runtime_is_unusable():
    for launcher_path in (Path("RUN.sh"), Path("RUN_DEV.sh")):
        function_source = _bash_function(
            launcher_path,
            "select_backend_cleanup_python",
        )
        harness = f"""
set -eu
temp_dir="$(mktemp -d "${{TMPDIR:-/tmp}}/vantage-cleanup.XXXXXX")"
trap 'rm -rf "$temp_dir"' EXIT
cd "$temp_dir"
BOOTSTRAP_PYTHON="bootstrap-python"
BACKEND_RUNTIME_PYTHON="runtime-python"
: > "$BOOTSTRAP_PYTHON"
: > "$BACKEND_RUNTIME_PYTHON"
chmod +x "$BOOTSTRAP_PYTHON" "$BACKEND_RUNTIME_PYTHON"
{function_source}
select_backend_cleanup_python
chmod -x "$BACKEND_RUNTIME_PYTHON"
select_backend_cleanup_python
rm -f "$BACKEND_RUNTIME_PYTHON"
select_backend_cleanup_python
rm -f "$BOOTSTRAP_PYTHON"
"""
        result = subprocess.run(
            ["bash", "-s"],
            input=harness.encode("utf-8"),
            capture_output=True,
            check=False,
        )

        stderr = result.stderr.decode("utf-8", errors="replace")
        stdout = result.stdout.decode("utf-8", errors="replace")
        assert result.returncode == 0, stderr
        assert stdout.splitlines() == [
            "runtime-python",
            "bootstrap-python",
            "bootstrap-python",
        ]


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

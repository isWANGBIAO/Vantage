#!/bin/bash
set -euo pipefail

echo "========================================"
echo "   Vantage - macOS Development Launcher"
echo "========================================"
echo

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

BACKEND_RUNTIME_VENV="${PROJECT_ROOT}/.venv-backend-runtime-gpu"
BACKEND_RUNTIME_PYTHON="${BACKEND_RUNTIME_VENV}/bin/python"
BACKEND_RUNTIME_CORE_REQUIREMENTS="${PROJECT_ROOT}/requirements-core.txt"
BACKEND_RUNTIME_REQUIREMENTS="${PROJECT_ROOT}/requirements-backend-runtime-gpu.txt"
OPENCV_NORMALIZER="${PROJECT_ROOT}/src/scripts/normalize_opencv_installation.py"
BACKEND_RUNTIME_SYNC="${PROJECT_ROOT}/src/scripts/sync_backend_runtime_environment.py"
BACKEND_RUNTIME_LOCK_RUNNER="${PROJECT_ROOT}/src/scripts/run_with_backend_runtime_lock.py"
BACKEND_RUNTIME_SIGNER="${PROJECT_ROOT}/src/scripts/sign_macos_backend_runtime.py"
MACOS_ARTIFACT_SIGNER="${PROJECT_ROOT}/src/scripts/sign_macos_artifacts.py"
BACKEND_RUNTIME_STATE="${BACKEND_RUNTIME_VENV}/.vantage-backend-runtime-state.json"
BACKEND_RUNTIME_CODESIGN_STAMP="${BACKEND_RUNTIME_VENV}/.macos-native-codesign.sha256"
LOCAL_BOOTSTRAP_PYTHON="${PROJECT_ROOT}/.local-python-3.13.5/bin/python3.13"
FRONTEND_ROOT="${PROJECT_ROOT}/src/webapp"
FRONTEND_NATIVE_CODESIGN_STAMP="${FRONTEND_ROOT}/node_modules/.macos-native-codesign.sha256"
PYTHON_BIN="${PYTHON_BIN:-$BACKEND_RUNTIME_PYTHON}"
BACKEND_STATUS_URL="${BACKEND_STATUS_URL:-http://127.0.0.1:8000/api/status}"
BACKEND_WAIT_TIMEOUT="${BACKEND_WAIT_TIMEOUT:-60}"
SERVER_LATEST_POINTER="${PROJECT_ROOT}/logs/server.latest.log"
export BACKEND_STATUS_URL BACKEND_WAIT_TIMEOUT SERVER_LATEST_POINTER
export PROJECT_ROOT PYTHON_BIN

python_supports_backend_venv() {
    local candidate="$1"
    local probe_pid waited status timed_out descendants monitor_was_enabled

    monitor_was_enabled=0
    case "$-" in
        *m*) monitor_was_enabled=1 ;;
    esac
    set -m
    "$candidate" -c 'import pathlib, sqlite3, ssl, subprocess, venv' >/dev/null 2>&1 &
    probe_pid=$!
    if (( monitor_was_enabled == 0 )); then
        set +m
    fi
    waited=0
    timed_out=0
    while kill -0 "$probe_pid" 2>/dev/null; do
        if (( waited >= 50 )); then
            timed_out=1
            break
        fi
        sleep 0.1
        waited=$((waited + 1))
    done

    if (( timed_out == 1 )); then
        status=1
    elif wait "$probe_pid"; then
        status=0
    else
        status=$?
    fi
    descendants=0
    if kill -0 -- "-$probe_pid" 2>/dev/null; then
        descendants=1
    fi
    if (( timed_out == 1 || descendants == 1 )); then
        kill -TERM -- "-$probe_pid" >/dev/null 2>&1 || true
        for _attempt in {1..10}; do
            if ! kill -0 -- "-$probe_pid" 2>/dev/null; then
                break
            fi
            sleep 0.1
        done
        kill -KILL -- "-$probe_pid" >/dev/null 2>&1 || true
        wait "$probe_pid" >/dev/null 2>&1 || true
        return 1
    fi
    return "$status"
}

resolve_bootstrap_python() {
    local candidates=()
    if [[ -n "${BOOTSTRAP_PYTHON:-}" ]]; then
        candidates+=("$BOOTSTRAP_PYTHON")
    fi
    candidates+=("/opt/homebrew/bin/python3.13" "$LOCAL_BOOTSTRAP_PYTHON")

    local path_python
    path_python="$(command -v python3 || true)"
    if [[ -n "$path_python" ]]; then
        candidates+=("$path_python")
    fi

    local candidate
    for candidate in "${candidates[@]}"; do
        if [[ -x "$candidate" ]] && python_supports_backend_venv "$candidate"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    echo "No usable Python found for backend runtime venv creation." >&2
    exit 1
}

BOOTSTRAP_PYTHON="$(resolve_bootstrap_python)"

select_backend_cleanup_python() {
    if [[ -x "$BACKEND_RUNTIME_PYTHON" ]]; then
        printf '%s\n' "$BACKEND_RUNTIME_PYTHON"
        return 0
    fi
    printf '%s\n' "$BOOTSTRAP_PYTHON"
}

codesign_macos_frontend_binaries() {
    if [[ "$(uname -s)" != "Darwin" || ! -d "${FRONTEND_ROOT}/node_modules" ]]; then
        return 0
    fi

    echo "      Ad-hoc signing macOS frontend native binaries..."
    local signer_args=(
        --project-root "$PROJECT_ROOT"
        --root "${FRONTEND_ROOT}/node_modules"
        --profile "frontend"
        --stamp "$FRONTEND_NATIVE_CODESIGN_STAMP"
    )
    if [[ "${VANTAGE_FORCE_MACOS_CODESIGN:-0}" == "1" ]]; then
        signer_args+=(--force)
    fi
    "$BOOTSTRAP_PYTHON" "$MACOS_ARTIFACT_SIGNER" "${signer_args[@]}"
}

echo "[0/4] Cleaning residual processes..."
BACKEND_CLEANUP_PYTHON="$(select_backend_cleanup_python)"
"$BACKEND_CLEANUP_PYTHON" src/scripts/cleanup_vantage_python_processes.py --include-desktop >/dev/null 2>&1 || true
echo "      Cleanup complete"
sleep 2

echo "[1/4] Preparing backend Python environment..."
backend_sync_args=(
    --project-root "$PROJECT_ROOT"
    --venv "$BACKEND_RUNTIME_VENV"
    --core-requirements "$BACKEND_RUNTIME_CORE_REQUIREMENTS"
    --requirements "$BACKEND_RUNTIME_REQUIREMENTS"
    --opencv-normalizer "$OPENCV_NORMALIZER"
)
if [[ "${VANTAGE_FORCE_BACKEND_DEPS:-0}" == "1" ]]; then
    backend_sync_args+=(--force)
fi
"$BOOTSTRAP_PYTHON" "$BACKEND_RUNTIME_SYNC" "${backend_sync_args[@]}"
backend_sign_args=(
    --project-root "$PROJECT_ROOT"
    --venv "$BACKEND_RUNTIME_VENV"
    --state "$BACKEND_RUNTIME_STATE"
    --stamp "$BACKEND_RUNTIME_CODESIGN_STAMP"
)
if [[ "${VANTAGE_FORCE_MACOS_CODESIGN:-0}" == "1" ]]; then
    backend_sign_args+=(--force)
fi
"$BOOTSTRAP_PYTHON" "$BACKEND_RUNTIME_SIGNER" "${backend_sign_args[@]}"

echo "[2/4] Starting backend..."
mkdir -p "${PROJECT_ROOT}/logs"
"$BOOTSTRAP_PYTHON" - "$BACKEND_RUNTIME_LOCK_RUNNER" "$PROJECT_ROOT" "$PYTHON_BIN" <<'PY'
import os
import subprocess
import sys
from pathlib import Path

lock_runner = Path(sys.argv[1])
project_root = Path(sys.argv[2])
python_bin = sys.argv[3]

subprocess.Popen(
    [
        sys.executable,
        str(lock_runner),
        "--project-root",
        str(project_root),
        "--",
        python_bin,
        "src/scripts/run_server_background.py",
    ],
    cwd=project_root,
    env=os.environ.copy(),
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    close_fds=True,
    start_new_session=True,
)
PY

echo "      Waiting for backend..."
"$BOOTSTRAP_PYTHON" - <<'PY'
import json
import os
import time
import urllib.request
from pathlib import Path

status_url = os.environ.get("BACKEND_STATUS_URL", "http://127.0.0.1:8000/api/status")
timeout = int(os.environ.get("BACKEND_WAIT_TIMEOUT", "60"))
latest_pointer = Path(os.environ.get("SERVER_LATEST_POINTER", "logs/server.latest.log"))
deadline = time.time() + timeout
last_error = None

while time.time() < deadline:
    try:
        with urllib.request.urlopen(status_url, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        camera = "online" if payload.get("camera_online") else "offline"
        print(f"      Backend ready (camera {camera})")
        raise SystemExit(0)
    except Exception as exc:
        last_error = exc
        elapsed = timeout - int(deadline - time.time())
        print(f"      Waiting for backend... {elapsed}/{timeout}s")
        time.sleep(1)

print(f"      Backend did not become ready within {timeout} seconds: {last_error}")
try:
    log_path = Path(latest_pointer.read_text(encoding="utf-8").strip())
    if log_path.exists():
        print(f"      Last 20 lines of {log_path}:")
        print("\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]))
except Exception:
    pass
raise SystemExit(1)
PY

echo "[3/4] Checking frontend dependencies..."
node "${FRONTEND_ROOT}/scripts/sync-dependencies.cjs" \
    --webapp-root "$FRONTEND_ROOT" \
    --invalidate-stamp "$FRONTEND_NATIVE_CODESIGN_STAMP"
codesign_macos_frontend_binaries

echo "[4/4] Launching Electron..."
echo "      Checking frontend build state..."
if node "${FRONTEND_ROOT}/check_build.js"; then
    echo "      Build is up to date"
else
    echo "      Build required, running npm run build..."
    npm --prefix "${FRONTEND_ROOT}" run build
fi

if [[ -f "${FRONTEND_ROOT}/dist/index.html" ]]; then
    echo "      Starting production Electron app in background..."
    "$BOOTSTRAP_PYTHON" src/scripts/run_frontend_background.py production
else
    echo "      Starting development Electron app in background..."
    "$BOOTSTRAP_PYTHON" src/scripts/run_frontend_background.py development
fi

echo
echo "========================================"
echo "   Development app launched in background"
echo "========================================"

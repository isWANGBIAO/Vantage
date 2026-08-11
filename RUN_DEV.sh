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
BACKEND_RUNTIME_STATE="${BACKEND_RUNTIME_VENV}/.vantage-backend-runtime-state.json"
BACKEND_RUNTIME_CODESIGN_STAMP="${BACKEND_RUNTIME_VENV}/.macos-native-codesign.sha256"
LOCAL_BOOTSTRAP_PYTHON="${PROJECT_ROOT}/.local-python-3.13.5/bin/python3.13"
FRONTEND_ROOT="${PROJECT_ROOT}/src/webapp"
FRONTEND_PACKAGE_LOCK="${FRONTEND_ROOT}/package-lock.json"
FRONTEND_NATIVE_CODESIGN_STAMP="${FRONTEND_ROOT}/node_modules/.macos-native-codesign.sha256"
PYTHON_BIN="${PYTHON_BIN:-$BACKEND_RUNTIME_PYTHON}"
BACKEND_STATUS_URL="${BACKEND_STATUS_URL:-http://127.0.0.1:8000/api/status}"
BACKEND_WAIT_TIMEOUT="${BACKEND_WAIT_TIMEOUT:-60}"
SERVER_LATEST_POINTER="${PROJECT_ROOT}/logs/server.latest.log"
export BACKEND_STATUS_URL BACKEND_WAIT_TIMEOUT SERVER_LATEST_POINTER
export PROJECT_ROOT PYTHON_BIN

python_supports_backend_venv() {
    local candidate="$1"
    local probe_file probe_pid waited status

    probe_file="$(mktemp "${TMPDIR:-/tmp}/vantage-python-probe.XXXXXX")" || return 1
    "$candidate" -c 'import pathlib, sqlite3, ssl, subprocess, venv' >"$probe_file" 2>&1 &
    probe_pid=$!
    waited=0
    while kill -0 "$probe_pid" 2>/dev/null; do
        if (( waited >= 5 )); then
            kill "$probe_pid" >/dev/null 2>&1 || true
            wait "$probe_pid" >/dev/null 2>&1 || true
            rm -f "$probe_file"
            return 1
        fi
        sleep 1
        waited=$((waited + 1))
    done

    wait "$probe_pid"
    status=$?
    rm -f "$probe_file"
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

codesign_macos_native_libraries() {
    if [[ "$(uname -s)" != "Darwin" ]]; then
        return 0
    fi

    local environment_state_hash
    environment_state_hash="$(shasum -a 256 "$BACKEND_RUNTIME_STATE" | awk '{print $1}')"
    local stored_codesign_hash=""
    if [[ -f "$BACKEND_RUNTIME_CODESIGN_STAMP" ]]; then
        stored_codesign_hash="$(cat "$BACKEND_RUNTIME_CODESIGN_STAMP")"
    fi
    if [[ "$environment_state_hash" == "$stored_codesign_hash" && "${VANTAGE_FORCE_MACOS_CODESIGN:-0}" != "1" ]]; then
        echo "      macOS native Python libraries already ad-hoc signed"
        return 0
    fi

    echo "      Ad-hoc signing macOS native Python libraries..."
    while IFS= read -r -d '' native_library; do
        if ! codesign --force --sign - "$native_library" >/dev/null 2>&1; then
            rm -f "$BACKEND_RUNTIME_CODESIGN_STAMP"
            echo "      macOS native Python library signing failed" >&2
            return 1
        fi
    done < <(find "${BACKEND_RUNTIME_VENV}/lib" -type f \( -name '*.so' -o -name '*.dylib' \) -print0)
    printf '%s\n' "$environment_state_hash" > "$BACKEND_RUNTIME_CODESIGN_STAMP"
}

codesign_macos_frontend_binaries() {
    if [[ "$(uname -s)" != "Darwin" || ! -d "${FRONTEND_ROOT}/node_modules" ]]; then
        return 0
    fi

    local package_lock_hash="no-package-lock"
    if [[ -f "$FRONTEND_PACKAGE_LOCK" ]]; then
        package_lock_hash="$(shasum -a 256 "$FRONTEND_PACKAGE_LOCK" | awk '{print $1}')"
    fi

    local stored_frontend_hash=""
    if [[ -f "$FRONTEND_NATIVE_CODESIGN_STAMP" ]]; then
        stored_frontend_hash="$(cat "$FRONTEND_NATIVE_CODESIGN_STAMP")"
    fi
    if [[ "$package_lock_hash" == "$stored_frontend_hash" && "${VANTAGE_FORCE_MACOS_CODESIGN:-0}" != "1" ]]; then
        echo "      macOS frontend native binaries already ad-hoc signed"
        return 0
    fi

    echo "      Ad-hoc signing macOS frontend native binaries..."
    xattr -dr com.apple.provenance "${FRONTEND_ROOT}/node_modules/@rollup" "${FRONTEND_ROOT}/node_modules/@esbuild" "${FRONTEND_ROOT}/node_modules/esbuild" "${FRONTEND_ROOT}/node_modules/app-builder-bin" >/dev/null 2>&1 || true
    find "${FRONTEND_ROOT}/node_modules" \
        -path "${FRONTEND_ROOT}/node_modules/electron" -prune -o \
        -type f \( -name '*.node' -o -name '*.dylib' -o -path '*/@esbuild/*/bin/esbuild' -o -path '*/esbuild/bin/esbuild' -o -path '*/app-builder-bin/mac/app-builder*' -o -path '*/7zip-bin/mac/*/7za' \) -print0 |
        while IFS= read -r -d '' native_binary; do
            codesign --force --sign - "$native_binary" >/dev/null 2>&1 || true
        done
    printf '%s\n' "$package_lock_hash" > "$FRONTEND_NATIVE_CODESIGN_STAMP"
}

echo "[0/4] Cleaning residual processes..."
"$BOOTSTRAP_PYTHON" src/scripts/cleanup_vantage_python_processes.py --include-desktop >/dev/null 2>&1 || true
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
codesign_macos_native_libraries

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

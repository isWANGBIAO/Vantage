#!/bin/bash
set -euo pipefail

echo "========================================"
echo "   Vantage - macOS Build and Install"
echo "========================================"
echo

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "RUN.sh is the macOS launcher. Use RUN.bat on Windows."
    exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

INSTALL_ROOT="${HOME}/Applications"
INSTALLED_APP="${INSTALL_ROOT}/Vantage.app"
VANTAGE_BUNDLE_ID="com.vantage.app"
BACKEND_RUNTIME_VENV="${PROJECT_ROOT}/.venv-backend-runtime-gpu"
BACKEND_RUNTIME_PYTHON="${BACKEND_RUNTIME_VENV}/bin/python"
BACKEND_RUNTIME_REQUIREMENTS="${PROJECT_ROOT}/requirements-backend-runtime-gpu.txt"
BACKEND_RUNTIME_REQUIREMENTS_STAMP="${BACKEND_RUNTIME_VENV}/.requirements-backend-runtime-gpu.sha256"
BACKEND_RUNTIME_CODESIGN_STAMP="${BACKEND_RUNTIME_VENV}/.macos-native-codesign.sha256"
LOCAL_BOOTSTRAP_PYTHON="${PROJECT_ROOT}/.local-python-3.13.5/bin/python3.13"
FRONTEND_ROOT="${PROJECT_ROOT}/src/webapp"
FRONTEND_PACKAGE_LOCK="${FRONTEND_ROOT}/package-lock.json"
FRONTEND_NATIVE_CODESIGN_STAMP="${FRONTEND_ROOT}/node_modules/.macos-native-codesign.sha256"
VANTAGE_BUILD_WORKERS="${VANTAGE_BUILD_WORKERS:-$(sysctl -n hw.ncpu 2>/dev/null || echo 2)}"

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

step_start() {
    STEP_START_SECONDS="$(date +%s)"
    echo "$1"
}

step_done() {
    local step_end_seconds
    step_end_seconds="$(date +%s)"
    echo "      $1 ($((step_end_seconds - STEP_START_SECONDS))s)"
}

codesign_macos_native_libraries() {
    local stored_codesign_hash=""
    if [[ -f "$BACKEND_RUNTIME_CODESIGN_STAMP" ]]; then
        stored_codesign_hash="$(cat "$BACKEND_RUNTIME_CODESIGN_STAMP")"
    fi
    if [[ "$requirements_hash" == "$stored_codesign_hash" && "${VANTAGE_FORCE_MACOS_CODESIGN:-0}" != "1" ]]; then
        echo "      macOS native Python libraries already ad-hoc signed"
        return 0
    fi

    echo "      Ad-hoc signing macOS native Python libraries..."
    find "${BACKEND_RUNTIME_VENV}/lib" -type f \( -name '*.so' -o -name '*.dylib' \) -print0 |
        while IFS= read -r -d '' native_library; do
            codesign --force --sign - "$native_library" >/dev/null 2>&1 || true
        done
    printf '%s\n' "$requirements_hash" > "$BACKEND_RUNTIME_CODESIGN_STAMP"
}

codesign_macos_frontend_binaries() {
    if [[ ! -d "${FRONTEND_ROOT}/node_modules" ]]; then
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

codesign_macos_backend_runtime_bundle() {
    local backend_runtime_dir="${PROJECT_ROOT}/build/backend-runtime/stage/VantageBackend"
    if [[ ! -d "$backend_runtime_dir" ]]; then
        return 0
    fi

    echo "      Ad-hoc signing packaged backend runtime binaries..."
    xattr -dr com.apple.provenance "$backend_runtime_dir" >/dev/null 2>&1 || true
    find "$backend_runtime_dir" -type f \( -name '*.so' -o -name '*.dylib' \) -print0 |
        while IFS= read -r -d '' runtime_binary; do
            codesign --force --sign - "$runtime_binary" >/dev/null 2>&1 || true
        done
}

prepare_macos_app_bundle() {
    local app_bundle="$1"
    if [[ ! -d "$app_bundle" ]]; then
        return 0
    fi

    echo "      Clearing installed macOS app bundle extended attributes..."
    xattr -cr "$app_bundle" >/dev/null 2>&1 || true
}

installed_app_bundle_id() {
    local app_bundle="$1"
    local info_plist="${app_bundle}/Contents/Info.plist"
    if [[ ! -f "$info_plist" ]]; then
        return 1
    fi

    /usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" "$info_plist" 2>/dev/null || true
}

terminate_installed_vantage_apps() {
    if [[ ! -d "$INSTALL_ROOT" ]]; then
        return 0
    fi

    local app_bundle bundle_id
    while IFS= read -r -d '' app_bundle; do
        bundle_id="$(installed_app_bundle_id "$app_bundle")"
        if [[ "$bundle_id" == "$VANTAGE_BUNDLE_ID" ]]; then
            pkill -f "${app_bundle}/Contents" >/dev/null 2>&1 || true
        fi
    done < <(find "$INSTALL_ROOT" -maxdepth 1 -type d -name '*.app' -print0)
}

remove_installed_vantage_apps() {
    mkdir -p "$INSTALL_ROOT"

    local app_bundle bundle_id
    while IFS= read -r -d '' app_bundle; do
        bundle_id="$(installed_app_bundle_id "$app_bundle")"
        if [[ "$bundle_id" == "$VANTAGE_BUNDLE_ID" ]]; then
            echo "      Removing installed Vantage bundle: ${app_bundle}"
            pkill -f "${app_bundle}/Contents" >/dev/null 2>&1 || true
            rm -rf "$app_bundle"
        fi
    done < <(find "$INSTALL_ROOT" -maxdepth 1 -type d -name '*.app' -print0)
}

clean_macos_package_outputs() {
    local dist_dir="${FRONTEND_ROOT}/electron-dist"
    if [[ ! -d "$dist_dir" ]]; then
        return 0
    fi

    echo "      Removing stale macOS package outputs..."
    rm -rf \
        "${dist_dir}/mac" \
        "${dist_dir}/mac-arm64" \
        "${dist_dir}/Vantage-"*.dmg \
        "${dist_dir}/Vantage-"*.zip \
        "${dist_dir}/Vantage-"*.blockmap \
        "${dist_dir}/builder-debug.yml"
}

RUN_START_SECONDS="$(date +%s)"

step_start "[0/8] Cleaning residual source processes..."
"$BOOTSTRAP_PYTHON" src/scripts/cleanup_vantage_python_processes.py --include-desktop >/dev/null 2>&1 || true
pkill -f "${INSTALLED_APP}/Contents" >/dev/null 2>&1 || true
terminate_installed_vantage_apps
step_done "Source cleanup complete"

step_start "[1/8] Checking frontend dependencies..."
if [[ ! -d "${FRONTEND_ROOT}/node_modules" ]]; then
    echo "      Installing dependencies..."
    npm --prefix "${FRONTEND_ROOT}" install
else
    echo "      Dependencies already installed"
fi
codesign_macos_frontend_binaries
step_done "Frontend dependency check complete"

step_start "[2/8] Preparing backend packaging environment..."
if [[ ! -x "$BACKEND_RUNTIME_PYTHON" ]]; then
    echo "      Creating clean backend runtime venv..."
    "$BOOTSTRAP_PYTHON" -m venv "$BACKEND_RUNTIME_VENV"
else
    echo "      Backend runtime venv already exists"
fi

requirements_hash="$(shasum -a 256 "$BACKEND_RUNTIME_REQUIREMENTS" | awk '{print $1}')"
stored_hash=""
if [[ -f "$BACKEND_RUNTIME_REQUIREMENTS_STAMP" ]]; then
    stored_hash="$(cat "$BACKEND_RUNTIME_REQUIREMENTS_STAMP")"
fi

if [[ "$requirements_hash" == "$stored_hash" && "${VANTAGE_FORCE_BACKEND_DEPS:-0}" != "1" ]]; then
    echo "      Backend runtime dependencies already synced"
else
    echo "      Syncing backend runtime dependencies..."
    "$BACKEND_RUNTIME_PYTHON" -m pip install --upgrade "pip==25.3"
    "$BACKEND_RUNTIME_PYTHON" -m pip install -r "$BACKEND_RUNTIME_REQUIREMENTS"
    printf '%s\n' "$requirements_hash" > "$BACKEND_RUNTIME_REQUIREMENTS_STAMP"
fi
codesign_macos_native_libraries
step_done "Backend packaging environment ready"

step_start "[3/8] Preparing build version..."
node "${FRONTEND_ROOT}/scripts/prepare-build-version.mjs" --webapp-root "${FRONTEND_ROOT}" --mode auto
step_done "Build version prepared"

step_start "[4/8] Building frontend and backend runtime in parallel..."
echo "      Build workers requested: ${VANTAGE_BUILD_WORKERS}"
"$BACKEND_RUNTIME_PYTHON" src/scripts/run_packaging_builds.py --backend-python "$BACKEND_RUNTIME_PYTHON" --workers "$VANTAGE_BUILD_WORKERS"
codesign_macos_backend_runtime_bundle
step_done "Frontend and backend build step complete"

step_start "[5/8] Verifying backend runtime..."
"$BACKEND_RUNTIME_PYTHON" src/scripts/verify_backend_runtime.py --timeout-seconds 300
step_done "Backend runtime verification complete"

step_start "[6/8] Building macOS app package..."
clean_macos_package_outputs
npm --prefix "${FRONTEND_ROOT}" run electron:package -- --mac
step_done "macOS app package build complete"

step_start "[7/8] Installing app into ~/Applications..."
app_path="$(find "${FRONTEND_ROOT}/electron-dist" -maxdepth 3 -type d -name 'Vantage.app' | sort | tail -n 1)"
if [[ -z "$app_path" ]]; then
    echo "      Built Vantage.app not found in src/webapp/electron-dist"
    exit 1
fi
remove_installed_vantage_apps
ditto "$app_path" "$INSTALLED_APP"
prepare_macos_app_bundle "$INSTALLED_APP"
step_done "App installed to ${INSTALLED_APP}"

step_start "[8/8] Launching Vantage..."
open -n "$INSTALLED_APP"
step_done "Launch command complete"

RUN_END_SECONDS="$(date +%s)"
echo
echo "========================================"
echo "   Build, install, and launch complete"
echo "   Total elapsed: $((RUN_END_SECONDS - RUN_START_SECONDS))s"
echo "========================================"

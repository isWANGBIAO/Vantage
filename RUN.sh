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
VANTAGE_BUILD_WORKERS="${VANTAGE_BUILD_WORKERS:-$(sysctl -n hw.ncpu 2>/dev/null || echo 2)}"

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

step_start() {
    STEP_START_SECONDS="$(date +%s)"
    echo "$1"
}

step_done() {
    local step_end_seconds
    step_end_seconds="$(date +%s)"
    echo "      $1 ($((step_end_seconds - STEP_START_SECONDS))s)"
}

codesign_macos_frontend_binaries() {
    if [[ ! -d "${FRONTEND_ROOT}/node_modules" ]]; then
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

codesign_macos_backend_runtime_bundle() {
    local backend_runtime_dir="${PROJECT_ROOT}/build/backend-runtime/stage/VantageBackend"
    if [[ ! -d "$backend_runtime_dir" ]]; then
        return 0
    fi

    echo "      Ad-hoc signing packaged backend runtime binaries..."
    "$BOOTSTRAP_PYTHON" "$MACOS_ARTIFACT_SIGNER" \
        --project-root "$PROJECT_ROOT" \
        --root "$backend_runtime_dir" \
        --profile "backend-bundle"
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

cleanup_macos_packaged_app_staging() {
    local staging_dir staging_app
    for staging_dir in "${FRONTEND_ROOT}/electron-dist/mac" "${FRONTEND_ROOT}/electron-dist/mac-arm64"; do
        staging_app="${staging_dir}/Vantage.app"
        if [[ -d "$staging_app" ]]; then
            echo "      Removing packaged staging app: ${staging_app}"
            rm -rf "$staging_app"
        fi
        if [[ -d "$staging_dir" ]] && [[ -z "$(find "$staging_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
            rmdir "$staging_dir" >/dev/null 2>&1 || true
        fi
    done
}

remove_path_with_retries() {
    local target="$1"
    local attempt
    if [[ ! -e "$target" ]]; then
        return 0
    fi

    for attempt in 1 2 3; do
        rm -rf "$target" >/dev/null 2>&1 || true
        if [[ ! -e "$target" ]]; then
            return 0
        fi
        find "$target" -name '.DS_Store' -delete >/dev/null 2>&1 || true
        sleep 1
    done

    rm -rf "$target"
}

clean_macos_package_outputs() {
    local dist_dir="${FRONTEND_ROOT}/electron-dist"
    if [[ ! -d "$dist_dir" ]]; then
        return 0
    fi

    echo "      Removing stale macOS package outputs..."
    local package_output
    for package_output in \
        "${dist_dir}/mac" \
        "${dist_dir}/mac-arm64" \
        "${dist_dir}/Vantage-"*.dmg \
        "${dist_dir}/Vantage-"*.zip \
        "${dist_dir}/Vantage-"*.blockmap \
        "${dist_dir}/builder-debug"*.yml; do
        remove_path_with_retries "$package_output"
    done
}

RUN_START_SECONDS="$(date +%s)"

step_start "[0/8] Cleaning residual source processes..."
BACKEND_CLEANUP_PYTHON="$(select_backend_cleanup_python)"
"$BACKEND_CLEANUP_PYTHON" src/scripts/cleanup_vantage_python_processes.py --include-desktop >/dev/null 2>&1 || true
pkill -f "${INSTALLED_APP}/Contents" >/dev/null 2>&1 || true
terminate_installed_vantage_apps
step_done "Source cleanup complete"

step_start "[1/8] Checking frontend dependencies..."
node "${FRONTEND_ROOT}/scripts/sync-dependencies.cjs" \
    --webapp-root "$FRONTEND_ROOT" \
    --invalidate-stamp "$FRONTEND_NATIVE_CODESIGN_STAMP"
codesign_macos_frontend_binaries
step_done "Frontend dependency check complete"

step_start "[2/8] Preparing backend packaging environment..."
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
step_done "Backend packaging environment ready"

step_start "[3/8] Preparing build version..."
node "${FRONTEND_ROOT}/scripts/prepare-build-version.mjs" --webapp-root "${FRONTEND_ROOT}" --mode auto
step_done "Build version prepared"

step_start "[4/8] Building frontend and backend runtime in parallel..."
echo "      Build workers requested: ${VANTAGE_BUILD_WORKERS}"
"$BOOTSTRAP_PYTHON" "$BACKEND_RUNTIME_LOCK_RUNNER" --project-root "$PROJECT_ROOT" -- \
    "$BACKEND_RUNTIME_PYTHON" src/scripts/run_packaging_builds.py \
    --backend-python "$BACKEND_RUNTIME_PYTHON" --workers "$VANTAGE_BUILD_WORKERS"
codesign_macos_backend_runtime_bundle
step_done "Frontend and backend build step complete"

step_start "[5/8] Verifying backend runtime..."
"$BOOTSTRAP_PYTHON" "$BACKEND_RUNTIME_LOCK_RUNNER" --project-root "$PROJECT_ROOT" -- \
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
cleanup_macos_packaged_app_staging
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

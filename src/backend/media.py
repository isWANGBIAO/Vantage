"""Media storage scanning, saved-photo publication, and media access routes."""

import asyncio
import os
import re
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from src.core.config import Config
from src.core.media_storage import (
    DEFAULT_LEGACY_MEDIA_ROOT,
    get_media_paths_settings_file,
    resolve_media_storage_paths,
)
from src.manager.take_photo.take_a_photo import PresencePhotoSaveCoordinator
from src.services.directory_size_scanner import DirectorySizeScanner
from src.services.person_detection import (
    PRESENCE_DETECTION_CONFIDENCE,
    detect_presence_count,
)
from src.utils.native_folders import open_directory

from . import camera as _camera
from . import observability as _observability
from . import plots as _plots
from . import runtime as _runtime
from . import security as _security

router = APIRouter()

STORAGE_SCAN_MAX_SECONDS = 3.0

STORAGE_SCAN_MAX_ENTRIES = 20000

STORAGE_SCAN_STATUS_LOG_INTERVAL_SECONDS = 3600.0

STORAGE_SCAN_REFRESH_INTERVAL_SECONDS = 15 * 60

STORAGE_STATS_UPDATE_INTERVAL_SECONDS = 60

LATEST_MEDIA_SCAN_MAX_SECONDS = 3.0

LATEST_MEDIA_SCAN_MAX_ENTRIES = 30000

_presence_photo_save_coordinator = PresencePhotoSaveCoordinator()

def _photo_capture_time_from_path(photo_path):
    try:
        photo_name = os.path.basename(os.fspath(photo_path))
    except (TypeError, ValueError):
        return None
    match = re.fullmatch(
        r"photo_(\d{8}_\d{6})\.jpg",
        photo_name,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
    except ValueError:
        return None

def _publish_presence_photo_path(photo_path):
    candidate_time = _photo_capture_time_from_path(photo_path)
    with _runtime.state.lock:
        current_path = _runtime.state.paths.get("photo")
        if photo_path == current_path:
            return True
        if candidate_time is None:
            return False
        current_time = _photo_capture_time_from_path(current_path)
        if current_time is not None and candidate_time < current_time:
            return False
        _runtime.state.paths["photo"] = photo_path
        return True

def _log_presence_photo_save_failure(exc):
    print(f"Camera presence photo save error: {exc}")

def _safe_directory_size(directory, *, max_seconds=STORAGE_SCAN_MAX_SECONDS, max_entries=STORAGE_SCAN_MAX_ENTRIES):
    total_size = 0
    skipped_count = 0
    visited_count = 0
    truncated = False
    deadline = time.monotonic() + max_seconds if max_seconds else None

    def onerror(exc):
        nonlocal skipped_count
        skipped_count += 1
        if skipped_count <= 3:
            print(f"Storage size scan skipped directory: {exc}")

    for root, dirs, files in os.walk(directory, onerror=onerror):
        dirs.sort(reverse=True)
        files.sort(reverse=True)
        for filename in files:
            visited_count += 1
            if max_entries and visited_count > max_entries:
                truncated = True
                break
            if deadline and time.monotonic() > deadline:
                truncated = True
                break
            file_path = os.path.join(root, filename)
            try:
                total_size += os.path.getsize(file_path)
            except OSError as exc:
                skipped_count += 1
                if skipped_count <= 3:
                    print(f"Storage size scan skipped file {file_path}: {exc}")
        if truncated:
            break

    if skipped_count > 3:
        print(f"Storage size scan skipped {skipped_count} entries under {directory}")
    if truncated:
        _observability._rate_limited_status_log(
            ("storage-size-budget", os.path.abspath(directory)),
            "Storage size scan budget reached under "
            f"{directory}; returning partial size",
            interval_seconds=STORAGE_SCAN_STATUS_LOG_INTERVAL_SECONDS,
        )
    _safe_directory_size.last_truncated = truncated
    return total_size

_safe_directory_size.last_truncated = False

def update_legacy_storage_stats():
    """Background task to calculate legacy storage usage once to avoid blocking main loop"""
    print("Starting background legacy storage scan...")
    try:
        total_size = 0

        # Candidates for legacy paths (OneDrive)
        candidates = []
        onedrive_env = os.environ.get("OneDrive")
        user_home = os.path.expanduser("~")

        roots_to_check = []
        if onedrive_env:
            roots_to_check.append(onedrive_env)
        roots_to_check.append(os.path.join(user_home, "OneDrive"))

        # STRICT SUBDIRECTORIES: Only folders created by THIS program
        subdirs = [
             os.path.join("Pictures", "本机照片"),
             os.path.join("图片", "本机照片"),
             os.path.join("Pictures", "Screenshots"),
             os.path.join("图片", "屏幕截图"),
             "本机照片",
             os.path.join("Pictures", "屏幕截图"),
             os.path.join("图片", "Screenshots")
        ]

        for root_dir in set(roots_to_check): # unique roots
            if root_dir and os.path.exists(root_dir):
                for sub in subdirs:
                    candidates.append(os.path.join(root_dir, sub))

        # Filter out invalid or current paths
        checked_paths = set()
        for cand in candidates:
            if not os.path.exists(cand): continue

            # Skip if current path
            if _runtime.state.photos_path and os.path.abspath(cand) == os.path.abspath(_runtime.state.photos_path): continue
            if _runtime.state.screenshots_path and os.path.abspath(cand) == os.path.abspath(_runtime.state.screenshots_path): continue

            # Avoid duplicates
            abs_cand = os.path.abspath(cand)
            if abs_cand in checked_paths: continue
            checked_paths.add(abs_cand)

            print(f"Scanning legacy path: {abs_cand}")
            total_size += _safe_directory_size(cand)

        _runtime.state.legacy_size = total_size
        print(f"Legacy storage scan complete: {_runtime.state.legacy_size / (1024**2):.2f} MB")

    except Exception as e:
        print(f"Legacy storage scan error: {e}")

def update_storage_stats(
    *,
    max_entries_per_step=STORAGE_SCAN_MAX_ENTRIES,
    max_seconds_per_step=STORAGE_SCAN_MAX_SECONDS,
    refresh_interval_seconds=STORAGE_SCAN_REFRESH_INTERVAL_SECONDS,
    monotonic_clock=None,
    sleep_fn=None,
    scanner_factory=DirectorySizeScanner,
):
    """Background thread to periodically update photos/screenshots storage size cache."""
    active_clock = monotonic_clock or time.monotonic
    active_sleep = sleep_fn or time.sleep
    scanners = {"photos": None, "screenshots": None}
    scanner_paths = {"photos": None, "screenshots": None}

    def close_scanner(key):
        scanner = scanners[key]
        scanners[key] = None
        scanner_paths[key] = None
        if scanner is None:
            return
        close = getattr(scanner, "close", None)
        if callable(close):
            try:
                close()
            except Exception as e:
                print(f"Storage scanner close error: {e}")

    try:
        while _runtime.state.is_running:
            try:
                scan_truncated = False
                sizes = {}
                for key, configured_path in (
                    ("photos", _runtime.state.photos_path),
                    ("screenshots", _runtime.state.screenshots_path),
                ):
                    normalized_path = (
                        os.path.abspath(os.fspath(configured_path))
                        if configured_path
                        else None
                    )
                    if not normalized_path:
                        close_scanner(key)
                        sizes[key] = 0
                        continue

                    if scanner_paths[key] != normalized_path:
                        close_scanner(key)
                        scanners[key] = scanner_factory(
                            normalized_path,
                            max_entries_per_step=max_entries_per_step,
                            max_seconds_per_step=max_seconds_per_step,
                            refresh_interval_seconds=refresh_interval_seconds,
                            monotonic_clock=active_clock,
                        )
                        scanner_paths[key] = normalized_path

                    snapshot = scanners[key].step()
                    sizes[key] = snapshot.total_size
                    scan_truncated = scan_truncated or not snapshot.complete

                _runtime.state.photos_size = sizes["photos"]
                _runtime.state.screenshots_size = sizes["screenshots"]
                _runtime.state.storage_scan_truncated = scan_truncated
            except Exception as e:
                print(f"Storage stats update error: {e}")
            active_sleep(STORAGE_STATS_UPDATE_INTERVAL_SECONDS)
    finally:
        for key in scanners:
            close_scanner(key)

def identify_logs_folder(
    *,
    config_dir: str | Path | None = None,
    user_home: str | None = None,
    onedrive_env: str | None = None,
    onedrive_consumer_env: str | None = None,
    d_drive_root: str = DEFAULT_LEGACY_MEDIA_ROOT,
):
    settings_file = get_media_paths_settings_file(config_dir=config_dir)
    return resolve_media_storage_paths(
        settings_file=settings_file,
        d_drive_root=d_drive_root,
        user_home=user_home,
        onedrive_env=onedrive_env,
        onedrive_consumer_env=onedrive_consumer_env,
    )

def find_latest_file_recursive(
    directory,
    extensions=None,
    *,
    max_seconds=LATEST_MEDIA_SCAN_MAX_SECONDS,
    max_entries=LATEST_MEDIA_SCAN_MAX_ENTRIES,
):
    if extensions is None:
        extensions = (".jpg", ".png")
    latest_file = None
    latest_time = 0
    visited_count = 0
    truncated = False
    deadline = time.monotonic() + max_seconds if max_seconds else None
    pending_dirs = [(float("inf"), os.path.abspath(directory))]
    visited_dirs = set()
    normalized_extensions = {ext.lower() for ext in extensions}

    def mark_truncated(message):
        nonlocal truncated
        truncated = True
        _observability._rate_limited_status_log(
            ("latest-media-budget", os.path.abspath(directory), message),
            message,
            interval_seconds=STORAGE_SCAN_STATUS_LOG_INTERVAL_SECONDS,
        )

    while pending_dirs:
        pending_dirs.sort(key=lambda item: item[0], reverse=True)
        directory_mtime, current_dir = pending_dirs.pop(0)
        if current_dir in visited_dirs:
            continue
        visited_dirs.add(current_dir)

        if latest_file and directory_mtime <= latest_time:
            continue

        file_candidates = []
        directory_candidates = []
        try:
            with os.scandir(current_dir) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stat_result = entry.stat(follow_symlinks=False)
                            directory_candidates.append((stat_result.st_mtime, entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            if os.path.splitext(entry.name)[1].lower() not in normalized_extensions:
                                continue
                            stat_result = entry.stat(follow_symlinks=False)
                            file_candidates.append((stat_result.st_mtime, entry.path))
                    except OSError:
                        continue
        except OSError:
            continue

        file_candidates.sort(key=lambda item: item[0], reverse=True)
        for mtime, full_path in file_candidates:
            if max_entries and visited_count >= max_entries:
                mark_truncated(
                    f"Latest media scan budget reached under {directory}; returning best match so far"
                )
                find_latest_file_recursive.last_truncated = truncated
                return latest_file
            if deadline and time.monotonic() > deadline:
                mark_truncated(
                    f"Latest media scan time budget reached under {directory}; returning best match so far"
                )
                find_latest_file_recursive.last_truncated = truncated
                return latest_file

            visited_count += 1
            if mtime > latest_time:
                latest_time = mtime
                latest_file = full_path

        for mtime, subdir in directory_candidates:
            if latest_file and mtime <= latest_time:
                continue
            pending_dirs.append((mtime, subdir))
    find_latest_file_recursive.last_truncated = truncated
    return latest_file

find_latest_file_recursive.last_truncated = False

def _prefer_primary_monitor_screenshot(screenshot_path):
    if not screenshot_path:
        return screenshot_path

    screenshot = Path(screenshot_path)
    match = re.match(r"^(screenshot_.+)_monitor_\d+(\.[^.]+)$", screenshot.name, re.IGNORECASE)
    if not match:
        return screenshot_path

    primary_screenshot = screenshot.with_name(f"{match.group(1)}_monitor_1{match.group(2)}")
    return str(primary_screenshot) if primary_screenshot.is_file() else screenshot_path

def _read_image_file(image_path):
    try:
        import numpy as np

        encoded = np.fromfile(os.fspath(image_path), dtype=np.uint8)
        if encoded.size == 0:
            return None
        return _camera.cv2.imdecode(encoded, _camera.cv2.IMREAD_COLOR)
    except Exception:
        return None

def _saved_photo_contains_person(photo_path):
    try:
        image = _read_image_file(photo_path)
        if image is None:
            print(f"Skipping latest photo that OpenCV cannot read: {photo_path}")
            return False

        person_count = detect_presence_count(image, conf=PRESENCE_DETECTION_CONFIDENCE)
        if person_count <= 0:
            print(f"Skipping latest photo without a detected person: {photo_path}")
            return False
        return True
    except Exception as exc:
        print(f"Skipping latest photo because person validation failed: {photo_path}: {exc}")
        return False

def initialize_latest_media_state():
    try:
        print("Scanning for latest existing images...")
        latest_media_scan_truncated = False
        if not _runtime.state.paths.get('photo') and _runtime.state.photos_path:
            latest_photo = find_latest_file_recursive(_runtime.state.photos_path)
            latest_media_scan_truncated = latest_media_scan_truncated or bool(
                getattr(find_latest_file_recursive, "last_truncated", False)
            )
            if latest_photo:
                if _saved_photo_contains_person(latest_photo):
                    _runtime.state.paths['photo'] = latest_photo
                    print(f"Found latest photo: {latest_photo}")

        if not _runtime.state.paths.get('screenshot') and _runtime.state.screenshots_path and _runtime.state.paths.get('photo'):
            latest_screen = find_latest_file_recursive(_runtime.state.screenshots_path)
            latest_media_scan_truncated = latest_media_scan_truncated or bool(
                getattr(find_latest_file_recursive, "last_truncated", False)
            )
            if latest_screen:
                latest_screen = _prefer_primary_monitor_screenshot(latest_screen)
                _runtime.state.paths['screenshot'] = latest_screen
                print(f"Found latest screenshot: {latest_screen}")
        elif not _runtime.state.paths.get('screenshot') and _runtime.state.screenshots_path:
            print("Skipping latest screenshot because no validated latest photo is available.")
        _runtime.state.latest_media_scan_truncated = latest_media_scan_truncated
    except Exception as e:
        print(f"Error finding latest files: {e}")

@router.post("/api/v1/media/open-folder")
async def open_folder(request: Request):
    if not _security._has_local_action_intent(request.headers, "open-folder"):
        return JSONResponse(status_code=403, content={"error": "Missing local action intent"})

    data = await request.json()
    folder_type = data.get("type")

    base_path = None
    if folder_type == "photo":
        base_path = _runtime.state.photos_path
    elif folder_type == "screenshot":
        base_path = _runtime.state.screenshots_path

    print(f"[OpenFolder] Request for type: {folder_type}, Base Path: {base_path}")

    if base_path and os.path.exists(base_path):
        try:
            # Construct hourly path: base / YYYY / MM / DD / HH
            now = datetime.now()
            year = now.strftime('%Y')
            month = now.strftime('%m')
            day = now.strftime('%d')
            hour = now.strftime('%H')

            # Try most specific path first, then fallback
            candidates = [
                os.path.join(base_path, year, month, day, hour),
                os.path.join(base_path, year, month, day),
                os.path.join(base_path, year, month),
                os.path.join(base_path, year),
                base_path
            ]

            target_path = base_path
            for path in candidates:
                if os.path.exists(path):
                    target_path = path
                    break

            print(f"[OpenFolder] Opening target path: {target_path}")

            await asyncio.to_thread(open_directory, target_path)
            return {"status": "success", "opened": target_path}
        except Exception as e:
            print(f"[OpenFolder] Error: {e}")
            return JSONResponse(status_code=500, content={"error": str(e)})

    print(f"[OpenFolder] Base path not found or invalid.")
    return JSONResponse(status_code=404, content={"error": "Folder path not found or not set"})

@router.get("/api/v1/media/latest")
def get_latest_images():
    try:
        photo_path = _runtime.state.paths.get('photo')
        screenshot_path = _runtime.state.paths.get('screenshot')

        photo_url = None
        if photo_path and _runtime.state.photos_path:
            try:
                rel_path = os.path.relpath(photo_path, _runtime.state.photos_path)
                rel_path = rel_path.replace("\\", "/") # Ensure web-friendly slashes
                photo_url = f"/static/photos/{rel_path}"
            except ValueError:
                photo_url = f"/static/photos/{os.path.basename(photo_path)}"

        screenshot_url = None
        if screenshot_path and _runtime.state.screenshots_path:
            try:
                # Always relative to screenshots_path mount
                rel_path = os.path.relpath(screenshot_path, _runtime.state.screenshots_path)
                rel_path = rel_path.replace("\\", "/")
                screenshot_url = f"/static/screenshots/{rel_path}"
            except ValueError:
                screenshot_url = f"/static/screenshots/{os.path.basename(screenshot_path)}"

        return {
            "photo": photo_url,
            "screenshot": screenshot_url,
            "photo_name": os.path.basename(photo_path) if photo_path else "",
            "screenshot_name": os.path.basename(screenshot_path) if screenshot_path else "",
            "latest_media_scan_truncated": _runtime.state.latest_media_scan_truncated,
        }
    except Exception as e:
        print(f"ERROR in get_latest_images: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/api/v1/media/image")
async def image_proxy(path: str):
    """Proxy endpoint to serve local images not in static directories"""
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "File not found"})

    # Security: only allow images with valid extensions
    valid_exts = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'}
    if os.path.splitext(path)[1].lower() not in valid_exts:
         return JSONResponse(status_code=400, content={"error": "Invalid file type"})

    # Security: restrict to allowed directories only
    abs_path = os.path.abspath(path)
    allowed_dirs = [
        _runtime.state.photos_path,
        _runtime.state.screenshots_path,
        str(_plots._get_plot_dir()),
        str(Config.get_history_dir()),
    ]
    def _is_within_allowed_dir(candidate_path, allowed_dir):
        if not allowed_dir:
            return False
        try:
            return os.path.commonpath([candidate_path, os.path.abspath(allowed_dir)]) == os.path.abspath(allowed_dir)
        except ValueError:
            return False

    if not any(_is_within_allowed_dir(abs_path, d) for d in allowed_dirs if d):
        return JSONResponse(status_code=403, content={"error": "Access denied: path not in allowed directories"})

    return FileResponse(abs_path)

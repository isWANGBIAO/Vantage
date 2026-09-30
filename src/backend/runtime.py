"""Shared hardware state, startup/shutdown lifecycle, and background thread ownership."""

import os
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from src.core.config import Config
from src.manager.manager_main import Monitor
from src.services.model_call_recorder import repair_abandoned_calls
from src.utils.data_loader import DataLoader
from src.utils.sensitive_data import register_runtime_log_path_prefixes

from . import camera as _camera
from . import face as _face
from . import media as _media
from . import plots as _plots

app = None

def bind_app(application):
    """Bind the composition root used only for lifespan-owned static mounts."""
    global app
    app = application

FOCUS_PRESENCE_STATE_FILENAME = "focus-presence-state.json"

# Global State
class SystemState:
    def __init__(self):
        self.camera = None
        self.renderer_camera = None
        self.renderer_camera_frame = None
        self.renderer_camera_last_seen_at = 0.0
        self.camera_release_queue = []
        self.camera_release_ids = set()
        self.monitor = None
        self.latest_frame = None
        self.latest_frame_published_at = None
        self.is_running = True
        self.camera_iteration_lock = threading.Lock()
        self.background_thread_status = {
            "camera_loop": False,
            "face_live_loop": False,
            "initialize_latest_media_state": False,
            "monitor_loop": False,
            "update_legacy_storage_stats": False,
            "update_storage_stats": False,
            "face_detection_loop": False,
        }
        self.lock = threading.Lock()
        self.paths = {'photo': None, 'screenshot': None}
        self.photos_path = None
        self.screenshots_path = None
        self.legacy_size = 0 # Cache for legacy storage size
        self.photos_size = 0  # Cache for photos storage size
        self.screenshots_size = 0  # Cache for screenshots storage size
        self.storage_scan_truncated = False
        self.latest_media_scan_truncated = False
        self.show_person_box = True
        self.person_boxes = []
        self.video_stream_client_count = 0
        self.live_face_points = deque()
        self.latest_live_face_score = None
        self.face_live_last_seen_at = 0.0
        self.last_processed_face_photo_path = None

state = SystemState()

def _mount_static_once(route_path, directory, name):
    if not directory or not os.path.exists(directory):
        return False

    normalized_directory = os.path.abspath(directory)
    for route in app.router.routes:
        if getattr(route, "path", None) != route_path:
            continue

        mounted_app = getattr(route, "app", None)
        current_directory = getattr(mounted_app, "directory", None)
        if current_directory is None or os.path.abspath(current_directory) != normalized_directory:
            route.app = StaticFiles(directory=directory)
            return False

        return False

    app.mount(route_path, StaticFiles(directory=directory), name=name)
    return True

def _start_background_thread_once(thread_name, target):
    with state.lock:
        if state.background_thread_status.get(thread_name):
            return False
        state.background_thread_status[thread_name] = True

    try:
        threading.Thread(target=target, daemon=True).start()
    except Exception:
        with state.lock:
            state.background_thread_status[thread_name] = False
        raise
    return True

async def startup_event():
    print("Starting up server...")
    state.is_running = True
    try:
        _camera.preflight_macos_camera_authorization()
    except Exception as e:
        print(f"Startup camera init error: {e}")

    # RESUME initialization (Unindented to run regardless of camera init success/failure)
    try:
        state.photos_path, state.screenshots_path = _media.identify_logs_folder()
        register_runtime_log_path_prefixes(
            {
                "<PHOTOS_ROOT>": state.photos_path,
                "<SCREENSHOTS_ROOT>": state.screenshots_path,
            }
        )
        print(f"----------------------------------------------------------------")
        print(f"[Storage] Photos Path: {state.photos_path}")
        print(f"[Storage] Screenshots Path: {state.screenshots_path}")
        print(f"----------------------------------------------------------------")

        state.monitor = Monitor(
            state.camera,
            state.paths,
            state.photos_path,
            state.screenshots_path,
            state_path=Path(Config.get_runtime_dir()) / FOCUS_PRESENCE_STATE_FILENAME,
            photo_path_publisher=_media._publish_presence_photo_path,
        )
        _face.prewarm_runtime_models()

        thread_specs = (
            ("camera_loop", _camera.camera_loop),
            ("face_live_loop", _camera.face_live_loop),
            ("monitor_loop", _camera.monitor_loop),
            ("update_legacy_storage_stats", _media.update_legacy_storage_stats),
            ("update_storage_stats", _media.update_storage_stats),
            ("face_detection_loop", _camera.face_detection_loop),
        )
        for thread_name, thread_target in thread_specs:
            _start_background_thread_once(thread_name, thread_target)

        # Mount static directories for photos and plots
        _mount_static_once("/static/photos", state.photos_path, "photos")

        plot_dir = _plots._get_plot_dir()
        plot_dir.mkdir(parents=True, exist_ok=True)
        _mount_static_once("/static/plots", plot_dir, "plots")

        _mount_static_once("/static/screenshots", state.screenshots_path, "screenshots")
        _start_background_thread_once("initialize_latest_media_state", _media.initialize_latest_media_state)

        # Records left in `started` by a process that was killed would otherwise
        # sit in the database forever and never appear in any usage total.
        try:
            removed_calls = repair_abandoned_calls()
            if removed_calls:
                print(f"[Usage] Cleared {removed_calls} abandoned in-flight call record(s)")
        except Exception as e:
            print(f"Usage record repair error: {e}")

        # Same failure mode for the workbook snapshots `_safe_copy_excel` takes:
        # a killed process never reaches its cleanup, so stale copies accumulate.
        try:
            removed_snapshots = DataLoader.cleanup_stale_excel_snapshots()
            if removed_snapshots:
                print(f"[Storage] Cleared {removed_snapshots} stale workbook snapshot(s)")
        except Exception as e:
            print(f"Workbook snapshot cleanup error: {e}")

    except Exception as e:
        print(f"Startup logic error: {e}")

async def shutdown_event():
    state.is_running = False
    for thread_name in state.background_thread_status:
        state.background_thread_status[thread_name] = False

    with state.camera_iteration_lock:
        with state.lock:
            camera = state.camera
            state.camera = None
            state.latest_frame = None
            state.latest_frame_published_at = None
            _camera._queue_camera_release_locked(camera)
        _camera._drain_camera_release_queue()

@asynccontextmanager
async def lifespan(_app):
    from . import application

    await startup_event()
    try:
        await application.start()
        yield
    finally:
        try:
            await application.stop()
        finally:
            await shutdown_event()

def sleep_while_running(seconds: float):
    deadline = time.monotonic() + max(0.0, seconds)
    while state.is_running:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(1.0, remaining))

def wait_for_next_inference_start(
    last_started_at: float | None,
    interval_seconds: float,
    *,
    monotonic_fn=None,
    sleep_fn=None,
):
    monotonic_fn = monotonic_fn or time.monotonic
    sleep_fn = sleep_fn or time.sleep
    next_allowed_at = (
        None
        if last_started_at is None
        else last_started_at + max(0.0, interval_seconds)
    )

    while True:
        now = monotonic_fn()
        if next_allowed_at is None or now >= next_allowed_at:
            return now
        sleep_fn(next_allowed_at - now)

"""Camera capture, renderer ingress, live inference loops, and video streaming."""

import math
import os
import sys
import time
from collections import deque
from datetime import datetime

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse

from src.manager.get_location import get_location
from src.manager.manager_main import Monitor
from src.services.person_detection import (
    PERSON_DETECTION_CONFIDENCE,
    PERSON_DETECTION_MODEL,
    PRESENCE_DETECTION_CONFIDENCE,
    detect_foreground_presence_face_boxes,
    get_face_detector,
)

from . import face as _face
from . import media as _media
from . import observability as _observability
from . import runtime as _runtime
from . import security as _security

router = APIRouter()

_cv2_module = None

RENDERER_CAMERA_FRAME_TTL_SECONDS = 5.0

MONITOR_FRAME_TTL_SECONDS = 5.0

RENDERER_CAMERA_MAX_FRAME_BYTES = 8 * 1024 * 1024

RENDERER_CAMERA_FRAME_INTENT = "renderer-camera-frame"

CAMERA_DARK_FRAME_MEAN_LUMA_THRESHOLD = 12.0

CAMERA_BLANK_FRAME_MEAN_LUMA_THRESHOLD = 1.0

CAMERA_BLANK_FRAME_RECOVERY_COUNT = int(os.environ.get("VANTAGE_CAMERA_BLANK_FRAME_RECOVERY_COUNT", "60"))

CAMERA_WARMUP_SECONDS = max(
    0.0,
    float(os.environ.get("VANTAGE_CAMERA_WARMUP_SECONDS", "2.0")),
)

def get_cv2_module():
    global _cv2_module
    if _cv2_module is None:
        import cv2 as loaded_cv2

        _cv2_module = loaded_cv2
    return _cv2_module

class _LazyCV2Module:
    def __getattr__(self, name):
        return getattr(get_cv2_module(), name)

cv2 = _LazyCV2Module()

FACE_LIVE_WINDOW_SECONDS = 60

FACE_LIVE_SAMPLE_INTERVAL_SECONDS = 1.0

FACE_DETECTION_SAMPLE_INTERVAL_SECONDS = 1.0

FACE_LIVE_IDLE_INTERVAL_SECONDS = 1.0

FACE_LIVE_VIEWER_TTL_SECONDS = 5.0

MONITOR_CAPTURE_INTERVAL_SECONDS = int(os.environ.get("VANTAGE_CAPTURE_INTERVAL_SECONDS", "60"))

MONITOR_CAMERA_WAIT_INTERVAL_SECONDS = 2.0

CAMERA_INDEX_OVERRIDE_ENV = "VANTAGE_CAMERA_INDEX"

MACOS_CAMERA_ENUMERATION_ENV = "VANTAGE_MACOS_ENUMERATE_CAMERAS"

MACOS_CAMERA_AUTH_PREFLIGHT_ENV = "VANTAGE_MACOS_CAMERA_AUTH_PREFLIGHT"

CAMERA_RETRY_INTERVAL_SECONDS = float(os.environ.get(
    "VANTAGE_CAMERA_RETRY_INTERVAL_SECONDS",
    "30" if sys.platform == "darwin" else "2",
))

CAMERA_STATUS_LOG_INTERVAL_SECONDS = float(os.environ.get(
    "VANTAGE_CAMERA_STATUS_LOG_INTERVAL_SECONDS",
    "300",
))

FACE_OVERLAY_BASE_SCORE_FONT_SCALE = 1.9

FACE_OVERLAY_SCORE_FONT_SCALE = FACE_OVERLAY_BASE_SCORE_FONT_SCALE * 2

FACE_OVERLAY_SCORE_THICKNESS = 8

FACE_OVERLAY_SCORE_PADDING = 24

FACE_OVERLAY_PERSON_FONT_SCALE = FACE_OVERLAY_BASE_SCORE_FONT_SCALE * 2

FACE_OVERLAY_PERSON_THICKNESS = 6

def _camera_online():
    camera = _runtime.state.camera
    if camera and camera.isOpened():
        return True
    return is_renderer_camera_active()

def is_renderer_camera_active(now_monotonic=None):
    try:
        now_monotonic = float(
            time.monotonic() if now_monotonic is None else now_monotonic
        )
        last_seen_at = float(
            getattr(_runtime.state, "renderer_camera_last_seen_at", 0.0) or 0.0
        )
    except (TypeError, ValueError):
        return False

    age_seconds = now_monotonic - last_seen_at
    return (
        getattr(_runtime.state, "renderer_camera_frame", None) is not None
        and math.isfinite(now_monotonic)
        and math.isfinite(last_seen_at)
        and 0.0 <= age_seconds <= RENDERER_CAMERA_FRAME_TTL_SECONDS
    )

class RendererCameraCapture:
    def isOpened(self):
        return is_renderer_camera_active()

    def read(self):
        with _runtime.state.lock:
            if not is_renderer_camera_active():
                return False, None
            frame = _runtime.state.renderer_camera_frame
            if frame is None:
                return False, None
            return True, frame.copy()

    def release(self):
        return None

def _clear_latest_frame_if_camera_is(expected_camera):
    with _runtime.state.lock:
        if _runtime.state.camera is not expected_camera:
            return False
        _runtime.state.latest_frame = None
        _runtime.state.latest_frame_published_at = None
        return True

def _install_camera_capture(camera):
    with _runtime.state.lock:
        if _runtime.state.camera is not None:
            return False
        _runtime.state.camera = camera
        _runtime.state.latest_frame = None
        _runtime.state.latest_frame_published_at = None
        return True

def _publish_camera_frame(camera, frame, published_at=None):
    with _runtime.state.lock:
        if _runtime.state.camera is not camera:
            return False
        if camera is _runtime.state.renderer_camera and is_renderer_camera_active():
            return True
        _runtime.state.latest_frame = frame
        _runtime.state.latest_frame_published_at = (
            time.monotonic() if published_at is None else float(published_at)
        )
        return True

def _queue_camera_release_locked(camera):
    if camera is None or camera is _runtime.state.renderer_camera:
        return False
    camera_id = id(camera)
    if camera_id in _runtime.state.camera_release_ids:
        return False
    _runtime.state.camera_release_ids.add(camera_id)
    _runtime.state.camera_release_queue.append(camera)
    return True

def _queue_camera_release(camera):
    with _runtime.state.lock:
        return _queue_camera_release_locked(camera)

def _drain_camera_release_queue():
    with _runtime.state.lock:
        pending = list(_runtime.state.camera_release_queue)
        _runtime.state.camera_release_queue.clear()

    for camera in pending:
        try:
            camera.release()
        except Exception as exc:
            print(f"Camera release error: {exc}")
        finally:
            with _runtime.state.lock:
                _runtime.state.camera_release_ids.discard(id(camera))

def _retire_camera_capture(camera):
    preserve_active_renderer = False
    retired = False
    with _runtime.state.lock:
        if _runtime.state.camera is camera:
            preserve_active_renderer = (
                camera is _runtime.state.renderer_camera and is_renderer_camera_active()
            )
            if not preserve_active_renderer:
                _runtime.state.camera = None
                _runtime.state.latest_frame = None
                _runtime.state.latest_frame_published_at = None
                retired = True
        if not preserve_active_renderer:
            _queue_camera_release_locked(camera)

    return retired

def calculate_frame_mean_luma(frame):
    if frame is None or getattr(frame, "size", 0) == 0:
        return None

    try:
        if len(frame.shape) >= 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame
        return float(gray.mean())
    except Exception as exc:
        print(f"Camera frame brightness check failed: {exc}")
        return None

def update_camera_blank_frame_streak(frame, current_streak):
    mean_luma = calculate_frame_mean_luma(frame)
    if mean_luma is None or mean_luma > CAMERA_BLANK_FRAME_MEAN_LUMA_THRESHOLD:
        return 0, False

    next_streak = max(0, int(current_streak or 0)) + 1
    return next_streak, next_streak >= CAMERA_BLANK_FRAME_RECOVERY_COUNT

def get_camera_warmup_deadline(opened_at=None):
    started_at = time.monotonic() if opened_at is None else float(opened_at)
    return started_at + CAMERA_WARMUP_SECONDS

def evaluate_camera_frame(
    frame,
    current_blank_streak,
    warmup_deadline,
    now_monotonic=None,
):
    now = time.monotonic() if now_monotonic is None else float(now_monotonic)
    warmup_complete = warmup_deadline is None or now >= float(warmup_deadline)
    if not warmup_complete:
        return 0, False, False

    next_streak, should_reopen = update_camera_blank_frame_streak(
        frame,
        current_blank_streak,
    )
    should_publish = next_streak == 0 and not should_reopen and warmup_complete
    return next_streak, should_reopen, should_publish

def _build_camera_frame_diagnostics():
    with _runtime.state.lock:
        frame = _runtime.state.latest_frame.copy() if _runtime.state.latest_frame is not None else None

    mean_luma = calculate_frame_mean_luma(frame)
    if mean_luma is None:
        return {
            "available": frame is not None,
            "dark": False,
            "mean_luma": None,
        }

    return {
        "available": True,
        "dark": mean_luma < CAMERA_DARK_FRAME_MEAN_LUMA_THRESHOLD,
        "mean_luma": round(mean_luma, 2),
    }

def _ensure_live_face_points_deque():
    if not isinstance(_runtime.state.live_face_points, deque):
        _runtime.state.live_face_points = deque(_runtime.state.live_face_points)

def _prune_live_face_points(now_ts=None):
    _ensure_live_face_points_deque()
    now_ts = float(now_ts if now_ts is not None else time.time())
    cutoff = now_ts - FACE_LIVE_WINDOW_SECONDS
    while _runtime.state.live_face_points and _runtime.state.live_face_points[0]["timestamp"] < cutoff:
        _runtime.state.live_face_points.popleft()

def store_live_face_result(result):
    if not result or not result.get("passed") or result.get("score") is None:
        return

    with _runtime.state.lock:
        _ensure_live_face_points_deque()
        _runtime.state.live_face_points.append(
            {
                "timestamp": float(result["timestamp"]),
                "datetime": result["datetime"],
                "score": float(result["score"]),
            }
        )
        _prune_live_face_points(result["timestamp"])

def snapshot_live_face_points(now_ts=None):
    with _runtime.state.lock:
        _prune_live_face_points(now_ts)
        return list(_runtime.state.live_face_points)

def update_live_face_overlay_state(result):
    latest_score = None
    if result and result.get("passed") and result.get("score") is not None:
        latest_score = float(result["score"])

    with _runtime.state.lock:
        _runtime.state.latest_live_face_score = latest_score

def format_live_face_score_label(score):
    if score is None or not math.isfinite(float(score)):
        return "Dark Circle Score: --"
    return f"Dark Circle Score: {float(score):.2f}"

def mark_face_live_viewer_active(now_ts=None):
    _runtime.state.face_live_last_seen_at = now_ts if now_ts is not None else time.time()

def has_active_face_live_viewer(now_ts=None):
    now_ts = now_ts if now_ts is not None else time.time()
    last_seen_at = getattr(_runtime.state, "face_live_last_seen_at", 0.0) or 0.0
    return (now_ts - last_seen_at) <= FACE_LIVE_VIEWER_TTL_SECONDS

def should_run_face_live_analysis(now_ts=None):
    return True

def register_video_stream_client():
    with _runtime.state.lock:
        _runtime.state.video_stream_client_count = max(0, getattr(_runtime.state, "video_stream_client_count", 0)) + 1

def unregister_video_stream_client():
    with _runtime.state.lock:
        _runtime.state.video_stream_client_count = max(0, getattr(_runtime.state, "video_stream_client_count", 0) - 1)

def has_active_video_stream_client():
    with _runtime.state.lock:
        return getattr(_runtime.state, "video_stream_client_count", 0) > 0

def should_run_face_detection():
    return True

# ... (existing imports/functions) ...

def get_camera_enumeration_backend(platform: str | None = None):
    resolved_platform = platform or sys.platform
    if resolved_platform == "win32":
        return getattr(cv2, "CAP_MSMF", cv2.CAP_ANY)
    if resolved_platform == "darwin":
        return getattr(cv2, "CAP_AVFOUNDATION", cv2.CAP_ANY)
    if resolved_platform.startswith("linux"):
        return getattr(cv2, "CAP_V4L2", cv2.CAP_ANY)
    return cv2.CAP_ANY

def get_camera_capture_backend(platform: str | None = None):
    resolved_platform = platform or sys.platform
    if resolved_platform == "win32":
        return getattr(cv2, "CAP_DSHOW", cv2.CAP_ANY)
    if resolved_platform == "darwin":
        return getattr(cv2, "CAP_AVFOUNDATION", cv2.CAP_ANY)
    if resolved_platform.startswith("linux"):
        return getattr(cv2, "CAP_V4L2", cv2.CAP_ANY)
    return cv2.CAP_ANY

def enumerate_available_cameras(platform: str | None = None):
    backend = get_camera_enumeration_backend(platform)
    try:
        from cv2_enumerate_cameras import enumerate_cameras

        return list(enumerate_cameras(backend))
    except Exception as exc:
        print(f"Camera enumeration failed for backend {backend}: {exc}")
        return []

def _camera_name_matches(camera_info, keywords):
    name = str(getattr(camera_info, "name", "") or "").lower()
    return any(keyword in name for keyword in keywords)

def get_camera_index(platform: str | None = None):
    resolved_platform = platform or sys.platform
    override = os.environ.get(CAMERA_INDEX_OVERRIDE_ENV)
    if override is not None:
        try:
            return max(0, int(override))
        except ValueError:
            print(f"Ignoring invalid {CAMERA_INDEX_OVERRIDE_ENV}: {override}")

    if (
        platform is None
        and resolved_platform == "darwin"
        and os.environ.get(MACOS_CAMERA_ENUMERATION_ENV) != "1"
    ):
        return 0

    camera_index = 0
    camera_infos = enumerate_available_cameras(resolved_platform)
    preferred_keywords = (
        ("usb camera", "usb") if resolved_platform == "win32" else ("facetime", "camera", "webcam")
    )
    for camera_info in camera_infos:
        if _camera_name_matches(camera_info, preferred_keywords):
            camera_index = camera_info.index
            break
    else:
        if camera_infos:
            camera_index = camera_infos[0].index
    return camera_index

def open_camera_capture(camera_index: int, platform: str | None = None):
    resolved_platform = platform or sys.platform
    backend = get_camera_capture_backend(resolved_platform)
    if backend == cv2.CAP_ANY:
        return cv2.VideoCapture(camera_index)

    camera = cv2.VideoCapture(camera_index, backend)
    if camera.isOpened():
        return camera

    camera.release()
    if resolved_platform == "darwin":
        return camera

    _observability._rate_limited_status_log(
        ("camera", "backend-fallback", resolved_platform, camera_index, backend),
        f"Camera backend {backend} failed for index {camera_index}; retrying with CAP_ANY",
        interval_seconds=CAMERA_STATUS_LOG_INTERVAL_SECONDS,
    )
    return cv2.VideoCapture(camera_index)

def preflight_macos_camera_authorization():
    if (
        sys.platform != "darwin"
        or os.environ.get("VANTAGE_APP_MODE") != "packaged"
        or os.environ.get(MACOS_CAMERA_AUTH_PREFLIGHT_ENV) != "1"
    ):
        return

    previous_skip_auth = os.environ.get("OPENCV_AVFOUNDATION_SKIP_AUTH")
    os.environ["OPENCV_AVFOUNDATION_SKIP_AUTH"] = "0"
    camera = None
    try:
        camera_index = get_camera_index("darwin")
        camera = cv2.VideoCapture(camera_index, get_camera_capture_backend("darwin"))
        print(
            "macOS camera authorization preflight "
            f"{'opened camera' if camera.isOpened() else 'did not open camera'}"
        )
    except Exception as exc:
        print(f"macOS camera authorization preflight failed: {exc}")
    finally:
        if camera is not None:
            camera.release()
        if previous_skip_auth is None:
            os.environ["OPENCV_AVFOUNDATION_SKIP_AUTH"] = "1"
        else:
            os.environ["OPENCV_AVFOUNDATION_SKIP_AUTH"] = previous_skip_auth

def _monitor_frame_timestamp_is_fresh(published_at, now_monotonic):
    return (
        isinstance(published_at, (int, float))
        and not isinstance(published_at, bool)
        and math.isfinite(published_at)
        and published_at <= now_monotonic
        and now_monotonic - published_at <= MONITOR_FRAME_TTL_SECONDS
    )

def run_monitor_capture_cycle():
    with _runtime.state.lock:
        monitor = _runtime.state.monitor
        source_camera = _runtime.state.camera
        frame = _runtime.state.latest_frame
        published_at = _runtime.state.latest_frame_published_at
        now_monotonic = time.monotonic()
        timestamp_is_fresh = _monitor_frame_timestamp_is_fresh(
            published_at,
            now_monotonic,
        )
        frame = frame.copy() if frame is not None and timestamp_is_fresh else None

    if monitor is None:
        return False

    def validate_observation_at_completion():
        with _runtime.state.lock:
            completed_at = time.monotonic()
            current_frame = _runtime.state.latest_frame
            current_published_at = _runtime.state.latest_frame_published_at
            return (
                _runtime.state.camera is source_camera
                and _monitor_frame_timestamp_is_fresh(
                    published_at,
                    completed_at,
                )
                and current_frame is not None
                and _monitor_frame_timestamp_is_fresh(
                    current_published_at,
                    completed_at,
                )
                and current_published_at >= published_at
            )

    observation_status = monitor.run_task(
        pre_captured_frame=frame,
        observation_validator=validate_observation_at_completion,
    )

    photo_path = _runtime.state.paths.get("photo")
    if photo_path and photo_path != _runtime.state.last_processed_face_photo_path:
        if _face.process_captured_face_photo(photo_path):
            _runtime.state.last_processed_face_photo_path = photo_path

    return observation_status in {Monitor.PRESENT, Monitor.ABSENT}

def monitor_loop():
    print(f"Starting monitor loop ({MONITOR_CAPTURE_INTERVAL_SECONDS}s interval)...")
    while _runtime.state.is_running:
        cycle_started_at = time.monotonic()
        capture_interval = MONITOR_CAMERA_WAIT_INTERVAL_SECONDS
        try:
            if run_monitor_capture_cycle():
                capture_interval = MONITOR_CAPTURE_INTERVAL_SECONDS
        except Exception as e:
            print(f"Monitor loop error: {e}")
        elapsed = time.monotonic() - cycle_started_at
        _runtime.sleep_while_running(capture_interval - elapsed)

def camera_loop():
    print(
        "Starting camera loop... "
        f"Backend: {get_camera_capture_backend()}"
    )
    blank_frame_streak = 0
    warmup_deadline = None
    while _runtime.state.is_running:
        with _runtime.state.camera_iteration_lock:
            if not _runtime.state.is_running:
                break

            _drain_camera_release_queue()
            if _runtime.state.camera is None:
                idx = get_camera_index()
                candidate = None
                try:
                    candidate = open_camera_capture(idx)
                    if not candidate or not candidate.isOpened():
                        _observability._rate_limited_status_log(
                            ("camera", "offline", idx),
                            f"Camera index {idx} is offline; retrying in {CAMERA_RETRY_INTERVAL_SECONDS:.0f}s",
                            interval_seconds=CAMERA_STATUS_LOG_INTERVAL_SECONDS,
                        )
                        if candidate:
                            _queue_camera_release(candidate)
                        _clear_latest_frame_if_camera_is(None)
                        _drain_camera_release_queue()
                        _runtime.sleep_while_running(CAMERA_RETRY_INTERVAL_SECONDS)
                        continue

                    if not _install_camera_capture(candidate):
                        _queue_camera_release(candidate)
                        _drain_camera_release_queue()
                        continue

                    # Request 4K resolution (16:9)
                    target_w, target_h = 3840, 2160
                    candidate.set(cv2.CAP_PROP_FRAME_WIDTH, target_w)
                    candidate.set(cv2.CAP_PROP_FRAME_HEIGHT, target_h)

                    # Verify actual resolution
                    actual_w = candidate.get(cv2.CAP_PROP_FRAME_WIDTH)
                    actual_h = candidate.get(cv2.CAP_PROP_FRAME_HEIGHT)
                    _observability.reset_camera_status_logs()
                    blank_frame_streak = 0
                    warmup_deadline = get_camera_warmup_deadline()
                    print(f"Camera Initialized: Requested {target_w}x{target_h}, Got {int(actual_w)}x{int(actual_h)}")

                    # If 4K failed (e.g. got low res), try strict 1080p fallback
                    if actual_w < 1280:
                        print("4K failed or ignored, trying strict 1080p force...")
                        candidate.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                        candidate.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                        print(f"Fallback resolution: {int(candidate.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(candidate.get(cv2.CAP_PROP_FRAME_HEIGHT))}")

                except Exception as e:
                    print(f"Camera init failed: {e}")
                    if candidate is None:
                        _clear_latest_frame_if_camera_is(None)
                    else:
                        _retire_camera_capture(candidate)
                    _drain_camera_release_queue()
                    _runtime.sleep_while_running(CAMERA_RETRY_INTERVAL_SECONDS)
                    continue

            camera = _runtime.state.camera
            if camera and camera.isOpened():
                try:
                    ret, frame = camera.read()
                    if ret:
                        (
                            blank_frame_streak,
                            should_reopen_camera,
                            should_publish_frame,
                        ) = evaluate_camera_frame(
                            frame, blank_frame_streak, warmup_deadline
                        )
                        if should_publish_frame:
                            _publish_camera_frame(camera, frame)
                            warmup_deadline = None
                        if should_reopen_camera:
                            _observability._rate_limited_status_log(
                                ("camera", "blank-frame-recovery"),
                                "Camera returned persistent blank frames; reopening capture",
                                interval_seconds=CAMERA_STATUS_LOG_INTERVAL_SECONDS,
                            )
                            retired = _retire_camera_capture(camera)
                            blank_frame_streak = 0
                            warmup_deadline = None
                            _drain_camera_release_queue()
                            if retired:
                                _runtime.sleep_while_running(0.5)
                    else:
                        print("Warning: Can't receive frame (stream end?). Exiting ...")
                        retired = _retire_camera_capture(camera)
                        warmup_deadline = None
                        _drain_camera_release_queue()
                        if retired:
                            _runtime.sleep_while_running(2)
                except Exception as e:
                    print(f"Camera read error: {e}")
                    retired = _retire_camera_capture(camera)
                    blank_frame_streak = 0
                    warmup_deadline = None
                    _drain_camera_release_queue()
                    if retired:
                        _runtime.sleep_while_running(1)
            else:
                print("Camera not opened, retrying...")
                if camera:
                    retired = _retire_camera_capture(camera)
                else:
                    retired = _clear_latest_frame_if_camera_is(None)
                warmup_deadline = None
                _drain_camera_release_queue()
                if retired:
                    _runtime.sleep_while_running(CAMERA_RETRY_INTERVAL_SECONDS)
            _drain_camera_release_queue()
        time.sleep(0.03)

def face_live_loop():
    print("Starting live face analysis loop...")
    last_inference_started_at = None
    while _runtime.state.is_running:
        if not should_run_face_live_analysis():
            time.sleep(FACE_LIVE_IDLE_INTERVAL_SECONDS)
            continue

        with _runtime.state.lock:
            frame_available = _runtime.state.latest_frame is not None

        if frame_available:
            try:
                detector, parser, config = _face.get_face_analysis_runtime()
                pipeline = _face.get_face_analysis_pipeline_module()
                _runtime.wait_for_next_inference_start(
                    last_inference_started_at,
                    FACE_LIVE_SAMPLE_INTERVAL_SECONDS,
                )
                if not _runtime.state.is_running:
                    break

                with _runtime.state.lock:
                    frame_copy = (
                        _runtime.state.latest_frame.copy()
                        if _runtime.state.latest_frame is not None
                        else None
                    )
                if frame_copy is None:
                    continue

                last_inference_started_at = time.monotonic()
                result = pipeline.analyze_image_data(
                    frame_copy,
                    detector=detector,
                    parser=parser,
                    config=config,
                )
                update_live_face_overlay_state(result)
                store_live_face_result(result)
            except Exception as exc:
                print(f"Live face analysis error: {exc}")
                if _runtime.state.is_running:
                    time.sleep(FACE_LIVE_IDLE_INTERVAL_SECONDS)
        else:
            time.sleep(FACE_LIVE_IDLE_INTERVAL_SECONDS)

def face_detection_loop():
    print("Starting foreground face detection background thread...")
    detector = None
    last_inference_started_at = None
    last_submitted_frame_published_at = None
    while _runtime.state.is_running:
        if detector is None:
            try:
                detector = get_face_detector()
                print("Camera face detector loaded successfully.")
            except Exception as e:
                with _runtime.state.lock:
                    _runtime.state.person_boxes = []
                print(f"Camera face detector unavailable in thread: {e}")
                time.sleep(FACE_LIVE_IDLE_INTERVAL_SECONDS)
                continue

        with _runtime.state.lock:
            frame_available = _runtime.state.latest_frame is not None

        if frame_available:
            inference_started_at = _runtime.wait_for_next_inference_start(
                last_inference_started_at,
                FACE_DETECTION_SAMPLE_INTERVAL_SECONDS,
            )
            if not _runtime.state.is_running:
                break
            frame_copy_error = None
            with _runtime.state.lock:
                published_at = _runtime.state.latest_frame_published_at
                frame_is_fresh = _monitor_frame_timestamp_is_fresh(
                    published_at,
                    inference_started_at,
                )
                if _runtime.state.latest_frame is None or not frame_is_fresh:
                    _runtime.state.person_boxes = []
                    frame_copy = None
                else:
                    try:
                        frame_copy = _runtime.state.latest_frame.copy()
                    except Exception as exc:
                        _runtime.state.person_boxes = []
                        frame_copy = None
                        frame_copy_error = exc
                photos_path = _runtime.state.photos_path
            if frame_copy is None:
                if frame_copy_error is not None:
                    print(f"Camera frame copy error: {frame_copy_error}")
                time.sleep(FACE_LIVE_IDLE_INTERVAL_SECONDS)
                continue

            last_inference_started_at = inference_started_at
            try:
                boxes = detect_foreground_presence_face_boxes(
                    frame_copy,
                    model=detector,
                    conf=PRESENCE_DETECTION_CONFIDENCE,
                )
            except Exception as e:
                with _runtime.state.lock:
                    _runtime.state.person_boxes = []
                print(f"Camera face detection error: {e}")
                continue

            with _runtime.state.lock:
                _runtime.state.person_boxes = boxes if _runtime.state.show_person_box else []

            if (
                boxes
                and photos_path
                and published_at != last_submitted_frame_published_at
            ):
                try:
                    _media._presence_photo_save_coordinator.submit(
                        frame_copy,
                        photos_path,
                        captured_at=datetime.now(),
                        location_provider=get_location,
                        on_success=_media._publish_presence_photo_path,
                        on_failure=_media._log_presence_photo_save_failure,
                    )
                except Exception as e:
                    _media._log_presence_photo_save_failure(e)
                else:
                    last_submitted_frame_published_at = published_at

        else:
            with _runtime.state.lock:
                _runtime.state.person_boxes = []
            time.sleep(FACE_LIVE_IDLE_INTERVAL_SECONDS)

def generate_frames():
    register_video_stream_client()
    try:
        while True:
            frame = None
            show_person_box = False
            face_boxes_copy = []
            with _runtime.state.lock:
                if _runtime.state.latest_frame is not None:
                    frame = _runtime.state.latest_frame.copy()
                overlay_score = _runtime.state.latest_live_face_score
                show_person_box = _runtime.state.show_person_box
                if show_person_box:
                    face_boxes_copy = list(_runtime.state.person_boxes)

            if frame is None:
                import numpy as np
                frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                cv2.putText(frame, "Camera Offline", (400, 360), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 2)

            if show_person_box:
                for (x1, y1, x2, y2) in face_boxes_copy:
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 3)
                    face_label = "Face"
                    (_, face_text_height), face_baseline = cv2.getTextSize(
                        face_label,
                        cv2.FONT_HERSHEY_SIMPLEX,
                        FACE_OVERLAY_PERSON_FONT_SCALE,
                        FACE_OVERLAY_PERSON_THICKNESS,
                    )
                    face_y = max(face_text_height + face_baseline + 8, y1 - 16)
                    cv2.putText(
                        frame,
                        face_label,
                        (x1, face_y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        FACE_OVERLAY_PERSON_FONT_SCALE,
                        (0, 255, 0),
                        FACE_OVERLAY_PERSON_THICKNESS,
                    )
                    score_label = format_live_face_score_label(overlay_score)
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    font_scale = FACE_OVERLAY_SCORE_FONT_SCALE
                    thickness = FACE_OVERLAY_SCORE_THICKNESS
                    padding = FACE_OVERLAY_SCORE_PADDING
                    (text_width, text_height), baseline = cv2.getTextSize(score_label, font, font_scale, thickness)
                    text_x = max(6, x2 - text_width)
                    text_y = max(text_height + baseline + padding, y1 - 12)
                    background_tl = (
                        max(0, text_x - padding),
                        max(0, text_y - text_height - baseline - padding),
                    )
                    background_br = (
                        min(frame.shape[1] - 1, text_x + text_width + padding),
                        min(frame.shape[0] - 1, text_y + padding),
                    )
                    cv2.rectangle(frame, background_tl, background_br, (0, 255, 0), -1)
                    cv2.putText(frame, score_label, (text_x, text_y), font, font_scale, (0, 0, 0), thickness)

            ret, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(0.04)
    finally:
        unregister_video_stream_client()

@router.get("/api/stream")
async def video_feed():
    return StreamingResponse(generate_frames(), media_type="multipart/x-mixed-replace; boundary=frame")

@router.post("/api/renderer_camera/frame")
async def receive_renderer_camera_frame(request: Request):
    if not _security._has_local_action_intent(request.headers, RENDERER_CAMERA_FRAME_INTENT):
        return JSONResponse(status_code=403, content={"error": "Missing local action intent"})

    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in {"image/jpeg", "image/jpg"}:
        return JSONResponse(status_code=415, content={"error": "Expected image/jpeg frame"})

    frame_bytes = await request.body()
    if not frame_bytes:
        return JSONResponse(status_code=400, content={"error": "Frame body is empty"})
    if len(frame_bytes) > RENDERER_CAMERA_MAX_FRAME_BYTES:
        return JSONResponse(status_code=413, content={"error": "Frame body is too large"})

    try:
        import numpy as np

        encoded = np.frombuffer(frame_bytes, dtype=np.uint8)
        frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": f"Frame decode failed: {exc}"})

    if frame is None:
        return JSONResponse(status_code=400, content={"error": "Frame decode failed"})

    with _runtime.state.lock:
        displaced_camera = _runtime.state.camera
        published_at = time.monotonic()
        if _runtime.state.renderer_camera is None:
            _runtime.state.renderer_camera = RendererCameraCapture()
        _runtime.state.renderer_camera_frame = frame
        _runtime.state.renderer_camera_last_seen_at = published_at
        _runtime.state.latest_frame = frame.copy()
        _runtime.state.latest_frame_published_at = published_at
        _runtime.state.camera = _runtime.state.renderer_camera
        if displaced_camera is not _runtime.state.renderer_camera:
            _queue_camera_release_locked(displaced_camera)

    return {
        "ok": True,
        "camera_online": _camera_online(),
        "width": int(frame.shape[1]),
        "height": int(frame.shape[0]),
    }

@router.post("/api/toggle_detection")
async def toggle_detection():
    with _runtime.state.lock:
        _runtime.state.show_person_box = not _runtime.state.show_person_box
        if not _runtime.state.show_person_box:
            _runtime.state.person_boxes = []  # Clear boxes immediately when turned off
    return {"status": "success", "show_person_box": _runtime.state.show_person_box}

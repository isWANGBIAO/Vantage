import asyncio
import os
import builtins
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from src import server
from src.manager.take_photo.get_best_photo import capture_best_photo


class _CameraLoopCapture:
    def __init__(
        self,
        *,
        opened=True,
        frame=None,
        read_error=None,
        release_error=None,
        on_read=None,
    ):
        self.opened = opened
        self.frame = frame
        self.read_error = read_error
        self.release_error = release_error
        self.on_read = on_read
        self.release_count = 0

    def isOpened(self):
        return self.opened

    def set(self, _property, _value):
        return True

    def get(self, _property):
        return 1920

    def read(self):
        if self.on_read is not None:
            return self.on_read()
        server.state.is_running = False
        if self.read_error is not None:
            raise self.read_error
        return self.frame

    def release(self):
        self.release_count += 1
        if self.release_error is not None:
            raise self.release_error


@pytest.fixture
def preserve_camera_loop_state():
    with server.state.lock:
        snapshot = {
            "camera": server.state.camera,
            "latest_frame": server.state.latest_frame,
            "latest_frame_published_at": getattr(
                server.state,
                "latest_frame_published_at",
                None,
            ),
            "renderer_camera": server.state.renderer_camera,
            "renderer_camera_frame": server.state.renderer_camera_frame,
            "renderer_camera_last_seen_at": server.state.renderer_camera_last_seen_at,
            "camera_release_queue": list(server.state.camera_release_queue),
            "camera_release_ids": set(server.state.camera_release_ids),
        }
    original_is_running = server.state.is_running
    try:
        yield
    finally:
        with server.state.lock:
            for name, value in snapshot.items():
                setattr(server.state, name, value)
            server.state.is_running = original_is_running


def test_monitor_capture_interval_defaults_to_one_minute():
    assert server.MONITOR_CAPTURE_INTERVAL_SECONDS == 60


def test_monitor_frame_ttl_is_independent_from_renderer_ttl(monkeypatch):
    monkeypatch.setattr(server, "RENDERER_CAMERA_FRAME_TTL_SECONDS", 0.25)

    assert server.MONITOR_FRAME_TTL_SECONDS == 5.0


def test_system_state_initializes_latest_frame_timestamp():
    fresh_state = server.SystemState()

    assert fresh_state.latest_frame is None
    assert fresh_state.latest_frame_published_at is None


def test_camera_frame_lifecycle_keeps_frame_and_timestamp_in_sync(
    monkeypatch,
    preserve_camera_loop_state,
):
    first_camera = _CameraLoopCapture(frame=(False, None))
    second_camera = _CameraLoopCapture(frame=(False, None))
    first_frame = np.full((8, 8, 3), 42, dtype=np.uint8)
    second_frame = np.full((8, 8, 3), 84, dtype=np.uint8)

    with server.state.lock:
        server.state.camera = None
        server.state.latest_frame = np.full((8, 8, 3), 1, dtype=np.uint8)
        server.state.latest_frame_published_at = 1.0

    assert server._install_camera_capture(first_camera) is True
    assert server.state.latest_frame is None
    assert server.state.latest_frame_published_at is None

    monkeypatch.setattr(server.time, "monotonic", lambda: 101.5)
    assert server._publish_camera_frame(first_camera, first_frame) is True
    assert server.state.latest_frame is first_frame
    assert server.state.latest_frame_published_at == 101.5

    assert server._retire_camera_capture(first_camera) is True
    assert server.state.latest_frame is None
    assert server.state.latest_frame_published_at is None

    assert server._install_camera_capture(second_camera) is True
    assert server._publish_camera_frame(
        second_camera,
        second_frame,
        published_at=202.5,
    ) is True
    assert server.state.latest_frame is second_frame
    assert server.state.latest_frame_published_at == 202.5

    assert server._clear_latest_frame_if_camera_is(second_camera) is True
    assert server.state.latest_frame is None
    assert server.state.latest_frame_published_at is None


def test_shutdown_clears_latest_frame_and_timestamp(
    preserve_camera_loop_state,
):
    with server.state.lock:
        server.state.camera = None
        server.state.latest_frame = np.full((8, 8, 3), 99, dtype=np.uint8)
        server.state.latest_frame_published_at = 303.5

    asyncio.run(server.shutdown_event())

    with server.state.lock:
        assert server.state.latest_frame is None
        assert server.state.latest_frame_published_at is None


def test_camera_backends_are_platform_specific():
    assert server.get_camera_enumeration_backend("win32") == getattr(cv2, "CAP_MSMF", cv2.CAP_ANY)
    assert server.get_camera_capture_backend("win32") == getattr(cv2, "CAP_DSHOW", cv2.CAP_ANY)
    assert server.get_camera_enumeration_backend("darwin") == getattr(cv2, "CAP_AVFOUNDATION", cv2.CAP_ANY)
    assert server.get_camera_capture_backend("darwin") == getattr(cv2, "CAP_AVFOUNDATION", cv2.CAP_ANY)


def test_get_camera_index_prefers_macos_camera_name():
    cameras = [
        SimpleNamespace(index=2, name="External Capture"),
        SimpleNamespace(index=1, name="FaceTime HD Camera"),
    ]

    with patch.object(server, "enumerate_available_cameras", return_value=cameras):
        assert server.get_camera_index("darwin") == 1


def test_get_camera_index_uses_macos_default_without_runtime_enumeration():
    with (
        patch.object(server.sys, "platform", "darwin"),
        patch.dict(os.environ, {server.MACOS_CAMERA_ENUMERATION_ENV: "0"}, clear=False),
        patch.object(
            server,
            "enumerate_available_cameras",
            side_effect=AssertionError("default macOS runtime path should avoid enumeration"),
        ),
    ):
        assert server.get_camera_index() == 0


def test_get_camera_index_honors_explicit_camera_index_override():
    with patch.dict(os.environ, {server.CAMERA_INDEX_OVERRIDE_ENV: "4"}, clear=False), patch.object(
        server,
        "enumerate_available_cameras",
        side_effect=AssertionError("override should avoid enumeration"),
    ):
        assert server.get_camera_index("darwin") == 4


def test_capture_best_photo_returns_none_when_camera_is_missing():
    assert capture_best_photo(None) is None


def test_persistent_pure_black_frames_trigger_camera_recovery():
    black_frame = np.zeros((8, 8, 3), dtype=np.uint8)
    streak = 0

    for _ in range(server.CAMERA_BLANK_FRAME_RECOVERY_COUNT - 1):
        streak, should_reopen = server.update_camera_blank_frame_streak(black_frame, streak)
        assert should_reopen is False

    streak, should_reopen = server.update_camera_blank_frame_streak(black_frame, streak)

    assert streak == server.CAMERA_BLANK_FRAME_RECOVERY_COUNT
    assert should_reopen is True


def test_dark_but_visible_frame_does_not_trigger_camera_recovery():
    visible_dark_frame = np.full((8, 8, 3), 5, dtype=np.uint8)

    streak, should_reopen = server.update_camera_blank_frame_streak(
        visible_dark_frame,
        server.CAMERA_BLANK_FRAME_RECOVERY_COUNT - 1,
    )

    assert streak == 0
    assert should_reopen is False


def test_camera_warmup_deadline_defaults_to_two_seconds():
    assert server.CAMERA_WARMUP_SECONDS == 2.0
    assert server.get_camera_warmup_deadline(100.0) == 102.0


def test_visible_camera_frame_is_not_published_before_warmup_completes():
    visible_frame = np.full((8, 8, 3), 128, dtype=np.uint8)

    streak, should_reopen, should_publish = server.evaluate_camera_frame(
        visible_frame,
        current_blank_streak=0,
        warmup_deadline=102.0,
        now_monotonic=101.99,
    )

    assert streak == 0
    assert should_reopen is False
    assert should_publish is False


def test_visible_camera_frame_is_published_when_warmup_completes():
    visible_frame = np.full((8, 8, 3), 128, dtype=np.uint8)

    streak, should_reopen, should_publish = server.evaluate_camera_frame(
        visible_frame,
        current_blank_streak=0,
        warmup_deadline=102.0,
        now_monotonic=102.0,
    )

    assert streak == 0
    assert should_reopen is False
    assert should_publish is True


def test_pure_black_camera_frame_is_never_published_after_warmup():
    black_frame = np.zeros((8, 8, 3), dtype=np.uint8)

    streak, should_reopen, should_publish = server.evaluate_camera_frame(
        black_frame,
        current_blank_streak=0,
        warmup_deadline=102.0,
        now_monotonic=103.0,
    )

    assert streak == 1
    assert should_reopen is False
    assert should_publish is False


def test_warmup_black_frames_do_not_carry_a_recovery_streak_past_deadline():
    black_frame = np.zeros((8, 8, 3), dtype=np.uint8)
    streak = 0

    for _ in range(server.CAMERA_BLANK_FRAME_RECOVERY_COUNT):
        streak, should_reopen, should_publish = server.evaluate_camera_frame(
            black_frame,
            current_blank_streak=streak,
            warmup_deadline=102.0,
            now_monotonic=101.99,
        )

        assert streak == 0
        assert should_reopen is False
        assert should_publish is False

    for frame_number in range(1, server.CAMERA_BLANK_FRAME_RECOVERY_COUNT + 1):
        streak, should_reopen, should_publish = server.evaluate_camera_frame(
            black_frame,
            current_blank_streak=streak,
            warmup_deadline=102.0,
            now_monotonic=102.0,
        )

        assert streak == frame_number
        assert should_reopen is (
            frame_number == server.CAMERA_BLANK_FRAME_RECOVERY_COUNT
        )
        assert should_publish is False


def test_camera_loop_clears_published_frame_when_blank_recovery_reopens_capture(
    monkeypatch,
    preserve_camera_loop_state,
):
    old_frame = np.full((8, 8, 3), 91, dtype=np.uint8)
    black_frame = np.zeros((8, 8, 3), dtype=np.uint8)
    capture = _CameraLoopCapture(frame=(True, black_frame))
    with server.state.lock:
        server.state.camera = capture
        server.state.latest_frame = old_frame
        server.state.is_running = True

    monkeypatch.setattr(server, "CAMERA_BLANK_FRAME_RECOVERY_COUNT", 1)
    monkeypatch.setattr(server, "_rate_limited_status_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)

    server.camera_loop()

    with server.state.lock:
        assert server.state.camera is None
        assert server.state.latest_frame is None
    assert capture.release_count == 1


@pytest.mark.parametrize(
    ("read_result", "read_error"),
    [
        ((False, None), None),
        (None, OSError("camera disconnected")),
    ],
    ids=("read-returned-false", "read-raised"),
)
def test_camera_loop_clears_published_frame_when_read_becomes_unavailable(
    monkeypatch,
    preserve_camera_loop_state,
    read_result,
    read_error,
):
    capture = _CameraLoopCapture(frame=read_result, read_error=read_error)
    with server.state.lock:
        server.state.camera = capture
        server.state.latest_frame = np.full((8, 8, 3), 92, dtype=np.uint8)
        server.state.is_running = True

    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)

    server.camera_loop()

    with server.state.lock:
        assert server.state.camera is None
        assert server.state.latest_frame is None
    assert capture.release_count == 1


def test_camera_loop_consumes_release_error_once_without_losing_control(
    monkeypatch,
    preserve_camera_loop_state,
):
    capture = _CameraLoopCapture(
        frame=(False, None),
        release_error=OSError("release failed"),
    )
    with server.state.lock:
        server.state.camera = capture
        server.state.latest_frame = np.full((8, 8, 3), 92, dtype=np.uint8)
        server.state.is_running = True

    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)

    server.camera_loop()

    with server.state.lock:
        assert server.state.camera is None
        assert server.state.latest_frame is None
    assert capture.release_count == 1


@pytest.mark.parametrize(
    "read_error",
    [None, OSError("camera disconnected")],
    ids=("read-returned-false", "read-raised"),
)
def test_shutdown_interrupts_camera_retry_delay_after_inflight_read(
    preserve_camera_loop_state,
    read_error,
):
    read_started = threading.Event()
    allow_read_to_finish = threading.Event()
    shutdown_finished = threading.Event()

    def blocking_read():
        read_started.set()
        allow_read_to_finish.wait(timeout=5)
        if read_error is not None:
            raise read_error
        return False, None

    capture = _CameraLoopCapture(on_read=blocking_read)
    with server.state.lock:
        server.state.camera = capture
        server.state.is_running = True

    camera_thread = threading.Thread(target=server.camera_loop)

    def run_shutdown():
        asyncio.run(server.shutdown_event())
        shutdown_finished.set()

    shutdown_thread = threading.Thread(target=run_shutdown)
    camera_thread.start()
    assert read_started.wait(timeout=2)
    shutdown_thread.start()

    deadline = time.monotonic() + 2
    while server.state.is_running and time.monotonic() < deadline:
        time.sleep(0.01)
    allow_read_to_finish.set()
    shutdown_completed_promptly = shutdown_finished.wait(timeout=0.5)

    camera_thread.join(timeout=3)
    shutdown_thread.join(timeout=3)

    assert shutdown_completed_promptly is True
    assert camera_thread.is_alive() is False
    assert shutdown_thread.is_alive() is False
    assert capture.release_count == 1


def test_camera_loop_clears_old_frame_before_new_capture_warmup(
    monkeypatch,
    preserve_camera_loop_state,
):
    visible_frame = np.full((8, 8, 3), 128, dtype=np.uint8)
    capture = _CameraLoopCapture(frame=(True, visible_frame))
    with server.state.lock:
        server.state.camera = None
        server.state.latest_frame = np.full((8, 8, 3), 93, dtype=np.uint8)
        server.state.is_running = True

    monkeypatch.setattr(server, "get_camera_index", lambda: 0)
    monkeypatch.setattr(server, "open_camera_capture", lambda _index: capture)
    monkeypatch.setattr(server, "get_camera_warmup_deadline", lambda: 102.0)
    monkeypatch.setattr(server.time, "monotonic", lambda: 101.0)
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)

    server.camera_loop()

    with server.state.lock:
        assert server.state.camera is capture
        assert server.state.latest_frame is None


def test_camera_loop_clears_old_frame_when_new_capture_fails_to_open(
    monkeypatch,
    preserve_camera_loop_state,
):
    capture = _CameraLoopCapture(opened=False)
    with server.state.lock:
        server.state.camera = None
        server.state.latest_frame = np.full((8, 8, 3), 94, dtype=np.uint8)
        server.state.is_running = True

    monkeypatch.setattr(server, "get_camera_index", lambda: 0)
    monkeypatch.setattr(server, "open_camera_capture", lambda _index: capture)
    monkeypatch.setattr(
        server,
        "sleep_while_running",
        lambda _seconds: setattr(server.state, "is_running", False),
    )

    server.camera_loop()

    with server.state.lock:
        assert server.state.camera is None
        assert server.state.latest_frame is None
    assert capture.release_count == 1


def test_camera_loop_does_not_clear_renderer_frame_that_takes_over_failed_capture(
    monkeypatch,
    preserve_camera_loop_state,
):
    renderer = server.RendererCameraCapture()
    renderer_frame = np.full((8, 8, 3), 127, dtype=np.uint8)

    def switch_to_renderer():
        with server.state.lock:
            server.state.renderer_camera = renderer
            server.state.renderer_camera_frame = renderer_frame
            server.state.renderer_camera_last_seen_at = server.time.time()
            server.state.camera = renderer
            server.state.latest_frame = renderer_frame.copy()
            server.state.is_running = False
        return False, None

    capture = _CameraLoopCapture(on_read=switch_to_renderer)
    with server.state.lock:
        server.state.camera = capture
        server.state.latest_frame = np.full((8, 8, 3), 95, dtype=np.uint8)
        server.state.is_running = True

    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)

    server.camera_loop()

    with server.state.lock:
        assert server.state.camera is renderer
        assert np.array_equal(server.state.latest_frame, renderer_frame)
    assert capture.release_count == 1


def test_macos_camera_open_does_not_fallback_to_cap_any_when_permission_is_missing():
    calls = []

    class FakeCapture:
        def __init__(self, *args):
            calls.append(args)

        def isOpened(self):
            return False

        def release(self):
            pass

    with patch.object(server.cv2, "VideoCapture", side_effect=lambda *args: FakeCapture(*args)):
        capture = server.open_camera_capture(3, "darwin")

    assert capture is not None
    assert calls == [(3, getattr(cv2, "CAP_AVFOUNDATION", cv2.CAP_ANY))]


def test_windows_camera_backend_fallback_log_is_rate_limited():
    class FakeCapture:
        def __init__(self, *args):
            self.args = args

        def isOpened(self):
            return False

        def release(self):
            pass

    now = {"value": 100.0}
    messages = []
    server.reset_camera_status_logs()
    try:
        with (
            patch.object(server.cv2, "VideoCapture", side_effect=lambda *args: FakeCapture(*args)),
            patch.object(server.time, "monotonic", side_effect=lambda: now["value"]),
            patch.object(builtins, "print", side_effect=lambda message: messages.append(message)),
        ):
            server.open_camera_capture(0, "win32")
            server.open_camera_capture(0, "win32")
            now["value"] += server.CAMERA_STATUS_LOG_INTERVAL_SECONDS + 1
            server.open_camera_capture(0, "win32")
    finally:
        server.reset_camera_status_logs()

    fallback_messages = [
        message for message in messages if "Camera backend" in message and "failed" in message
    ]
    assert len(fallback_messages) == 2
    assert "suppressed 1 repeat" in fallback_messages[-1]


def test_macos_camera_auth_preflight_temporarily_enables_avfoundation_auth():
    calls = []

    class FakeCapture:
        def __init__(self, *args):
            calls.append(args)

        def isOpened(self):
            return False

        def release(self):
            calls.append(("release",))

    with (
        patch.object(server.sys, "platform", "darwin"),
        patch.dict(
            os.environ,
            {
                "VANTAGE_APP_MODE": "packaged",
                server.MACOS_CAMERA_AUTH_PREFLIGHT_ENV: "1",
                "OPENCV_AVFOUNDATION_SKIP_AUTH": "1",
            },
            clear=False,
        ),
        patch.object(server, "get_camera_index", return_value=0),
        patch.object(server.cv2, "VideoCapture", side_effect=lambda *args: FakeCapture(*args)),
    ):
        server.preflight_macos_camera_authorization()
        assert os.environ["OPENCV_AVFOUNDATION_SKIP_AUTH"] == "1"

    assert calls == [(0, getattr(cv2, "CAP_AVFOUNDATION", cv2.CAP_ANY)), ("release",)]

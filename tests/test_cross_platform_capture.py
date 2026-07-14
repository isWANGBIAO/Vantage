import os
import builtins
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from src import server
from src.manager.take_photo.get_best_photo import capture_best_photo


def test_monitor_capture_interval_defaults_to_one_minute():
    assert server.MONITOR_CAPTURE_INTERVAL_SECONDS == 60


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

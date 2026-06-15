import os
from types import SimpleNamespace
from unittest.mock import patch

import cv2

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

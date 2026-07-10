import os

import numpy as np
import pytest

from src.manager.screenshot import take_a_screenshot as screenshot_module


class EmptyMssContext:
    monitors = [{"left": 0, "top": 0, "width": 0, "height": 0}]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def test_macos_screencapture_fallback_when_mss_has_no_displays(monkeypatch, tmp_path):
    run_calls = []
    saved = {}

    def fake_run(args, check):
        run_calls.append((args, check))

    def fake_save_image(path, img, latitude, longitude):
        saved["path"] = path
        saved["img"] = img
        saved["latitude"] = latitude
        saved["longitude"] = longitude

    monkeypatch.setattr(screenshot_module.sys, "platform", "darwin")
    monkeypatch.setattr(screenshot_module.mss, "mss", lambda: EmptyMssContext())
    monkeypatch.setattr(screenshot_module.subprocess, "run", fake_run)
    monkeypatch.setattr(screenshot_module.cv2, "imread", lambda path, flags: "image-data")
    monkeypatch.setattr(screenshot_module, "save_image_with_gps", fake_save_image)

    result = screenshot_module.take_and_save_screenshots(12.3, 45.6, str(tmp_path))

    assert result == saved["path"]
    assert os.path.basename(result).startswith("screenshot_")
    assert os.path.basename(result).endswith("_monitor_1.jpg")
    assert run_calls[0][0][0:2] == ["screencapture", "-x"]
    assert run_calls[0][1] is True
    assert saved["img"] == "image-data"
    assert saved["latitude"] == 12.3
    assert saved["longitude"] == 45.6


@pytest.mark.parametrize(
    "physical_monitors",
    [
        [
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
            {"left": -1080, "top": -290, "width": 1080, "height": 1920},
        ],
        [
            {"left": -1080, "top": -290, "width": 1080, "height": 1920},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
        ],
    ],
)
def test_multi_monitor_capture_returns_primary_screen_for_latest_ui(
    monkeypatch,
    tmp_path,
    physical_monitors,
):
    virtual_monitor = {"left": -1080, "top": -290, "width": 3000, "height": 1920}
    saved_shapes = {}

    class MultiMonitorMssContext:
        monitors = [virtual_monitor, *physical_monitors]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def grab(self, monitor):
            return np.zeros((monitor["height"], monitor["width"], 4), dtype=np.uint8)

    def fake_save_image(path, img, latitude, longitude):
        saved_shapes[os.path.basename(path)] = img.shape

    monkeypatch.setattr(screenshot_module.mss, "mss", lambda: MultiMonitorMssContext())
    monkeypatch.setattr(screenshot_module, "save_image_with_gps", fake_save_image)

    result = screenshot_module.take_and_save_screenshots(12.3, 45.6, str(tmp_path))

    assert os.path.basename(result).endswith("_monitor_1.jpg")
    assert saved_shapes[os.path.basename(result)] == (1080, 1920, 3)
    assert sorted(saved_shapes.values()) == [(1080, 1920, 3), (1920, 1080, 3)]

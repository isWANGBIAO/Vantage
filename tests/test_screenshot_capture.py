import os

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

import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src import server


def _write_synthetic_jpeg(path):
    image = np.zeros((9, 13, 3), dtype=np.uint8)
    image[:, :, 1] = 180
    encoded_ok, encoded = server.get_cv2_module().imencode(".jpg", image)
    if not encoded_ok:
        raise AssertionError("OpenCV failed to encode synthetic JPEG")
    path.write_bytes(encoded.tobytes())
    return image.shape


class LatestImagesEndpointTests(unittest.TestCase):
    def test_read_image_file_loads_jpeg_from_unicode_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            photo_path = Path(tmpdir) / "合成照片-测试.jpg"
            expected_shape = _write_synthetic_jpeg(photo_path)

            image = server._read_image_file(photo_path)

        self.assertIsInstance(image, np.ndarray)
        self.assertEqual(image.shape, expected_shape)

    def test_saved_photo_uses_raw_presence_detection_for_unicode_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            photo_path = Path(tmpdir) / "侧脸历史照片.jpg"
            expected_shape = _write_synthetic_jpeg(photo_path)

            with patch.object(
                server,
                "detect_presence_count",
                return_value=1,
            ) as detect_presence:
                contains_person = server._saved_photo_contains_person(photo_path)

        self.assertTrue(contains_person)
        detected_image = detect_presence.call_args.args[0]
        self.assertIsInstance(detected_image, np.ndarray)
        self.assertEqual(detected_image.shape, expected_shape)
        self.assertEqual(
            detect_presence.call_args.kwargs["conf"],
            server.PRESENCE_DETECTION_CONFIDENCE,
        )

    def test_saved_photo_rejects_corrupt_and_unreadable_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            empty_path = tmp / "空照片.jpg"
            empty_path.write_bytes(b"")
            corrupt_path = tmp / "损坏照片.jpg"
            corrupt_path.write_bytes(b"not an image")
            unreadable_path = tmp / "不存在照片.jpg"

            for photo_path in (empty_path, corrupt_path, unreadable_path):
                with self.subTest(photo_path=photo_path):
                    self.assertIsNone(server._read_image_file(photo_path))
                    with patch.object(
                        server,
                        "detect_presence_count",
                        create=True,
                    ) as detect_presence:
                        self.assertFalse(server._saved_photo_contains_person(photo_path))
                    detect_presence.assert_not_called()

    def test_get_latest_images_reports_scan_truncation_flag(self):
        original_paths = dict(server.state.paths)
        original_photos_path = server.state.photos_path
        original_screenshots_path = server.state.screenshots_path
        original_latest_media_scan_truncated = server.state.latest_media_scan_truncated

        try:
            server.state.paths = {"photo": None, "screenshot": None}
            server.state.photos_path = None
            server.state.screenshots_path = None
            server.state.latest_media_scan_truncated = True

            payload = server.get_latest_images()
        finally:
            server.state.paths = original_paths
            server.state.photos_path = original_photos_path
            server.state.screenshots_path = original_screenshots_path
            server.state.latest_media_scan_truncated = original_latest_media_scan_truncated

        self.assertTrue(payload["latest_media_scan_truncated"])

    def test_initialize_latest_media_state_tracks_truncated_scans(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            photos_dir = tmp / "photos"
            screenshots_dir = tmp / "screenshots"
            photos_dir.mkdir()
            screenshots_dir.mkdir()
            (photos_dir / "photo.jpg").write_bytes(b"a")
            (screenshots_dir / "screen.png").write_bytes(b"b")

            original_paths = dict(server.state.paths)
            original_photos_path = server.state.photos_path
            original_screenshots_path = server.state.screenshots_path
            original_latest_media_scan_truncated = server.state.latest_media_scan_truncated

            try:
                server.state.paths = {"photo": None, "screenshot": None}
                server.state.photos_path = str(photos_dir)
                server.state.screenshots_path = str(screenshots_dir)
                server.state.latest_media_scan_truncated = False

                with patch.object(server, "_saved_photo_contains_person", return_value=True):
                    server.initialize_latest_media_state()
            finally:
                truncated = server.state.latest_media_scan_truncated
                photo_path = server.state.paths.get("photo")
                screenshot_path = server.state.paths.get("screenshot")
                server.state.paths = original_paths
                server.state.photos_path = original_photos_path
                server.state.screenshots_path = original_screenshots_path
                server.state.latest_media_scan_truncated = original_latest_media_scan_truncated

        self.assertFalse(truncated)
        self.assertTrue(str(photo_path).endswith("photo.jpg"))
        self.assertTrue(str(screenshot_path).endswith("screen.png"))

    def test_initialize_latest_media_state_skips_unvalidated_latest_photo_and_screenshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            photos_dir = tmp / "photos"
            screenshots_dir = tmp / "screenshots"
            photos_dir.mkdir()
            screenshots_dir.mkdir()
            (photos_dir / "empty-room.jpg").write_bytes(b"a")
            (screenshots_dir / "screen.png").write_bytes(b"b")

            original_paths = dict(server.state.paths)
            original_photos_path = server.state.photos_path
            original_screenshots_path = server.state.screenshots_path
            original_latest_media_scan_truncated = server.state.latest_media_scan_truncated

            try:
                server.state.paths = {"photo": None, "screenshot": None}
                server.state.photos_path = str(photos_dir)
                server.state.screenshots_path = str(screenshots_dir)
                server.state.latest_media_scan_truncated = False

                with patch.object(server, "_saved_photo_contains_person", return_value=False):
                    server.initialize_latest_media_state()
            finally:
                photo_path = server.state.paths.get("photo")
                screenshot_path = server.state.paths.get("screenshot")
                server.state.paths = original_paths
                server.state.photos_path = original_photos_path
                server.state.screenshots_path = original_screenshots_path
                server.state.latest_media_scan_truncated = original_latest_media_scan_truncated

        self.assertIsNone(photo_path)
        self.assertIsNone(screenshot_path)

    def test_initialize_latest_media_state_prefers_primary_monitor_from_latest_capture(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            photos_dir = tmp / "photos"
            screenshots_dir = tmp / "screenshots"
            photos_dir.mkdir()
            screenshots_dir.mkdir()
            (photos_dir / "photo.jpg").write_bytes(b"photo")
            primary = screenshots_dir / "screenshot_20260710_194604_monitor_1.jpg"
            secondary = screenshots_dir / "screenshot_20260710_194604_monitor_2.jpg"
            primary.write_bytes(b"primary")
            secondary.write_bytes(b"secondary")
            os.utime(primary, (100, 100))
            os.utime(secondary, (101, 101))

            original_paths = dict(server.state.paths)
            original_photos_path = server.state.photos_path
            original_screenshots_path = server.state.screenshots_path
            original_latest_media_scan_truncated = server.state.latest_media_scan_truncated

            try:
                server.state.paths = {"photo": None, "screenshot": None}
                server.state.photos_path = str(photos_dir)
                server.state.screenshots_path = str(screenshots_dir)
                server.state.latest_media_scan_truncated = False

                with patch.object(server, "_saved_photo_contains_person", return_value=True):
                    server.initialize_latest_media_state()
                screenshot_path = server.state.paths.get("screenshot")
            finally:
                server.state.paths = original_paths
                server.state.photos_path = original_photos_path
                server.state.screenshots_path = original_screenshots_path
                server.state.latest_media_scan_truncated = original_latest_media_scan_truncated

        self.assertEqual(Path(screenshot_path).name, primary.name)


if __name__ == "__main__":
    unittest.main()

import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from src import server


class LatestImagesEndpointTests(unittest.TestCase):
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

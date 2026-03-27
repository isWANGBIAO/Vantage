import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch

from src import server


class _DummyThread:
    started_count = 0

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def start(self):
        _DummyThread.started_count += 1


def test_startup_event_is_idempotent_for_static_mounts_and_threads():
    original_routes = list(server.app.router.routes)
    original_photos = server.state.photos_path
    original_screenshots = server.state.screenshots_path
    original_monitor = server.state.monitor
    original_paths = dict(server.state.paths)
    original_startup_initialized = server.state.startup_initialized

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            photos_path = tmp_path / "photos"
            screenshots_path = tmp_path / "screenshots"
            photos_path.mkdir()
            screenshots_path.mkdir()

            _DummyThread.started_count = 0

            with (
                patch.object(server, "identify_logs_folder", return_value=(str(photos_path), str(screenshots_path))),
                patch.object(server, "find_latest_file_recursive", return_value=None),
                patch.object(server, "Monitor", side_effect=lambda *args, **kwargs: object()),
                patch.object(server.threading, "Thread", _DummyThread),
                patch.object(server.os, "getcwd", return_value=tmp_dir),
            ):
                first_route_count = len(server.app.router.routes)

                asyncio.run(server.startup_event())
                after_first_startup = len(server.app.router.routes)
                asyncio.run(server.startup_event())
                after_second_startup = len(server.app.router.routes)

            assert after_first_startup == first_route_count + 3
            assert after_second_startup == after_first_startup
            assert _DummyThread.started_count == 6
    finally:
        server.app.router.routes[:] = original_routes
        server.state.photos_path = original_photos
        server.state.screenshots_path = original_screenshots
        server.state.monitor = original_monitor
        server.state.paths = original_paths
        server.state.startup_initialized = original_startup_initialized


def test_startup_event_can_run_again_after_shutdown():
    original_routes = list(server.app.router.routes)
    original_photos = server.state.photos_path
    original_screenshots = server.state.screenshots_path
    original_monitor = server.state.monitor
    original_paths = dict(server.state.paths)
    original_running = server.state.is_running
    original_startup_initialized = server.state.startup_initialized

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            photos_path = tmp_path / "photos"
            screenshots_path = tmp_path / "screenshots"
            photos_path.mkdir()
            screenshots_path.mkdir()

            _DummyThread.started_count = 0

            with (
                patch.object(server, "identify_logs_folder", return_value=(str(photos_path), str(screenshots_path))),
                patch.object(server, "find_latest_file_recursive", return_value=None),
                patch.object(server, "Monitor", side_effect=lambda *args, **kwargs: object()),
                patch.object(server.threading, "Thread", _DummyThread),
                patch.object(server.os, "getcwd", return_value=tmp_dir),
            ):
                asyncio.run(server.startup_event())
                after_first_startup = len(server.app.router.routes)

                asyncio.run(server.shutdown_event())

                asyncio.run(server.startup_event())
                after_second_startup = len(server.app.router.routes)

            assert after_second_startup == after_first_startup
            assert _DummyThread.started_count == 12
    finally:
        server.app.router.routes[:] = original_routes
        server.state.photos_path = original_photos
        server.state.screenshots_path = original_screenshots
        server.state.monitor = original_monitor
        server.state.paths = original_paths
        server.state.is_running = original_running
        server.state.startup_initialized = original_startup_initialized

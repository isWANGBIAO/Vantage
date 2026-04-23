import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from src import server

STATIC_ROUTE_PATHS = (
    "/static/photos",
    "/static/plots",
    "/static/screenshots",
)


class _DummyThread:
    started_count = 0

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def start(self):
        _DummyThread.started_count += 1


class _PartiallyFailingThread:
    start_counts = {}
    failure_seen = False

    def __init__(self, *args, **kwargs):
        self.target = kwargs.get("target")

    def start(self):
        target_name = getattr(self.target, "__name__", str(self.target))
        _PartiallyFailingThread.start_counts[target_name] = _PartiallyFailingThread.start_counts.get(target_name, 0) + 1
        if target_name == "update_legacy_storage_stats" and not _PartiallyFailingThread.failure_seen:
            _PartiallyFailingThread.failure_seen = True
            raise RuntimeError("simulated thread start failure")


def _static_route_directories():
    directories = {}
    for route in server.app.router.routes:
        route_path = getattr(route, "path", None)
        if route_path in STATIC_ROUTE_PATHS:
            directories[route_path] = os.path.abspath(getattr(getattr(route, "app", None), "directory", ""))
    return directories


def test_startup_event_is_idempotent_for_static_mounts_and_threads():
    original_routes = list(server.app.router.routes)
    original_photos = server.state.photos_path
    original_screenshots = server.state.screenshots_path
    original_monitor = server.state.monitor
    original_paths = dict(server.state.paths)
    original_background_thread_status = dict(server.state.background_thread_status)

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
                patch.object(server.Config, "get_plot_dir", return_value=tmp_path / "plot_outputs"),
            ):
                asyncio.run(server.startup_event())
                after_first_startup = _static_route_directories()
                asyncio.run(server.startup_event())
                after_second_startup = _static_route_directories()

            assert after_first_startup == {
                "/static/photos": os.path.abspath(str(photos_path)),
                "/static/plots": os.path.abspath(str(tmp_path / "plot_outputs")),
                "/static/screenshots": os.path.abspath(str(screenshots_path)),
            }
            assert after_second_startup == after_first_startup
            assert _DummyThread.started_count == 7
    finally:
        server.app.router.routes[:] = original_routes
        server.state.photos_path = original_photos
        server.state.screenshots_path = original_screenshots
        server.state.monitor = original_monitor
        server.state.paths = original_paths
        server.state.background_thread_status = original_background_thread_status


def test_startup_event_prewarms_runtime_models_before_background_threads():
    original_routes = list(server.app.router.routes)
    original_photos = server.state.photos_path
    original_screenshots = server.state.screenshots_path
    original_monitor = server.state.monitor
    original_paths = dict(server.state.paths)
    original_background_thread_status = dict(server.state.background_thread_status)

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            photos_path = tmp_path / "photos"
            screenshots_path = tmp_path / "screenshots"
            photos_path.mkdir()
            screenshots_path.mkdir()

            events = []

            def record_prewarm():
                events.append("prewarm")

            class _RecordingThread:
                def __init__(self, *args, **kwargs):
                    self.target = kwargs.get("target")

                def start(self):
                    events.append(f"thread:{getattr(self.target, '__name__', 'unknown')}")

            with (
                patch.object(server, "identify_logs_folder", return_value=(str(photos_path), str(screenshots_path))),
                patch.object(server, "find_latest_file_recursive", return_value=None),
                patch.object(server, "Monitor", side_effect=lambda *args, **kwargs: object()),
                patch.object(server, "prewarm_runtime_models", side_effect=record_prewarm),
                patch.object(server.threading, "Thread", _RecordingThread),
                patch.object(server.Config, "get_plot_dir", return_value=tmp_path / "plot_outputs"),
            ):
                asyncio.run(server.startup_event())

            assert events[0] == "prewarm"
            assert any(event.startswith("thread:") for event in events[1:])
    finally:
        server.app.router.routes[:] = original_routes
        server.state.photos_path = original_photos
        server.state.screenshots_path = original_screenshots
        server.state.monitor = original_monitor
        server.state.paths = original_paths
        server.state.background_thread_status = original_background_thread_status


def test_startup_event_retries_partial_failure_without_duplicate_threads():
    original_routes = list(server.app.router.routes)
    original_photos = server.state.photos_path
    original_screenshots = server.state.screenshots_path
    original_monitor = server.state.monitor
    original_paths = dict(server.state.paths)
    original_running = server.state.is_running
    original_background_thread_status = dict(server.state.background_thread_status)

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            photos_path = tmp_path / "photos"
            screenshots_path = tmp_path / "screenshots"
            photos_path.mkdir()
            screenshots_path.mkdir()

            _DummyThread.started_count = 0

            call_count = {"count": 0}

            def flaky_find_latest_file_recursive(*args, **kwargs):
                call_count["count"] += 1
                if call_count["count"] == 1:
                    raise RuntimeError("simulated scan failure")
                return None

            with (
                patch.object(server, "identify_logs_folder", return_value=(str(photos_path), str(screenshots_path))),
                patch.object(server, "find_latest_file_recursive", side_effect=flaky_find_latest_file_recursive),
                patch.object(server, "Monitor", side_effect=lambda *args, **kwargs: object()),
                patch.object(server.threading, "Thread", _DummyThread),
                patch.object(server.Config, "get_plot_dir", return_value=tmp_path / "plot_outputs"),
            ):
                asyncio.run(server.startup_event())
                asyncio.run(server.startup_event())
                after_retry = _static_route_directories()

            assert after_retry == {
                "/static/photos": os.path.abspath(str(photos_path)),
                "/static/plots": os.path.abspath(str(tmp_path / "plot_outputs")),
                "/static/screenshots": os.path.abspath(str(screenshots_path)),
            }
            assert _DummyThread.started_count == 7
    finally:
        server.app.router.routes[:] = original_routes
        server.state.photos_path = original_photos
        server.state.screenshots_path = original_screenshots
        server.state.monitor = original_monitor
        server.state.paths = original_paths
        server.state.is_running = original_running
        server.state.background_thread_status = original_background_thread_status


def test_startup_event_updates_static_mounts_after_shutdown():
    original_routes = list(server.app.router.routes)
    original_photos = server.state.photos_path
    original_screenshots = server.state.screenshots_path
    original_monitor = server.state.monitor
    original_paths = dict(server.state.paths)
    original_running = server.state.is_running
    original_background_thread_status = dict(server.state.background_thread_status)

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            photos_path_1 = tmp_path / "photos_1"
            screenshots_path_1 = tmp_path / "screenshots_1"
            photos_path_2 = tmp_path / "photos_2"
            screenshots_path_2 = tmp_path / "screenshots_2"
            for path in (photos_path_1, screenshots_path_1, photos_path_2, screenshots_path_2):
                path.mkdir()

            _DummyThread.started_count = 0

            with (
                patch.object(
                    server,
                    "identify_logs_folder",
                    side_effect=[
                        (str(photos_path_1), str(screenshots_path_1)),
                        (str(photos_path_2), str(screenshots_path_2)),
                    ],
                ),
                patch.object(server, "find_latest_file_recursive", return_value=None),
                patch.object(server, "Monitor", side_effect=lambda *args, **kwargs: object()),
                patch.object(server.threading, "Thread", _DummyThread),
                patch.object(server.Config, "get_plot_dir", return_value=tmp_path / "plot_outputs"),
            ):
                asyncio.run(server.startup_event())
                first_mounts = _static_route_directories()
                asyncio.run(server.shutdown_event())
                asyncio.run(server.startup_event())
                second_mounts = _static_route_directories()

            assert first_mounts == {
                "/static/photos": os.path.abspath(str(photos_path_1)),
                "/static/plots": os.path.abspath(str(tmp_path / "plot_outputs")),
                "/static/screenshots": os.path.abspath(str(screenshots_path_1)),
            }
            assert second_mounts == {
                "/static/photos": os.path.abspath(str(photos_path_2)),
                "/static/plots": os.path.abspath(str(tmp_path / "plot_outputs")),
                "/static/screenshots": os.path.abspath(str(screenshots_path_2)),
            }
            assert _DummyThread.started_count == 14
    finally:
        server.app.router.routes[:] = original_routes
        server.state.photos_path = original_photos
        server.state.screenshots_path = original_screenshots
        server.state.monitor = original_monitor
        server.state.paths = original_paths
        server.state.is_running = original_running
        server.state.background_thread_status = original_background_thread_status


def test_startup_event_resumes_only_missing_threads_after_partial_start_failure():
    original_routes = list(server.app.router.routes)
    original_photos = server.state.photos_path
    original_screenshots = server.state.screenshots_path
    original_monitor = server.state.monitor
    original_paths = dict(server.state.paths)
    original_running = server.state.is_running
    original_background_thread_status = dict(server.state.background_thread_status)

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            photos_path = tmp_path / "photos"
            screenshots_path = tmp_path / "screenshots"
            photos_path.mkdir()
            screenshots_path.mkdir()

            _PartiallyFailingThread.start_counts = {}
            _PartiallyFailingThread.failure_seen = False

            with (
                patch.object(server, "identify_logs_folder", return_value=(str(photos_path), str(screenshots_path))),
                patch.object(server, "find_latest_file_recursive", return_value=None),
                patch.object(server, "Monitor", side_effect=lambda *args, **kwargs: object()),
                patch.object(server.threading, "Thread", _PartiallyFailingThread),
                patch.object(server.Config, "get_plot_dir", return_value=tmp_path / "plot_outputs"),
            ):
                asyncio.run(server.startup_event())
                after_first_startup = dict(_PartiallyFailingThread.start_counts)
                asyncio.run(server.startup_event())
                after_retry = dict(_PartiallyFailingThread.start_counts)

            assert after_first_startup == {
                "camera_loop": 1,
                "face_live_loop": 1,
                "monitor_loop": 1,
                "update_legacy_storage_stats": 1,
            }
            assert after_retry == {
                "camera_loop": 1,
                "face_live_loop": 1,
                "initialize_latest_media_state": 1,
                "monitor_loop": 1,
                "update_legacy_storage_stats": 2,
                "update_storage_stats": 1,
                "yolo_loop": 1,
            }
            assert _static_route_directories() == {
                "/static/photos": os.path.abspath(str(photos_path)),
                "/static/plots": os.path.abspath(str(tmp_path / "plot_outputs")),
                "/static/screenshots": os.path.abspath(str(screenshots_path)),
            }
    finally:
        server.app.router.routes[:] = original_routes
        server.state.photos_path = original_photos
        server.state.screenshots_path = original_screenshots
        server.state.monitor = original_monitor
        server.state.paths = original_paths
        server.state.is_running = original_running
        server.state.background_thread_status = original_background_thread_status

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.backend import face as _backend_face
from src.backend import media as _backend_media
from src.backend import plots as _backend_plots
from src.backend import runtime as _backend_runtime
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


def test_startup_registers_media_roots_before_logging_or_monitor_creation():
    original_routes = list(server.app.router.routes)
    original_photos = _backend_runtime.state.photos_path
    original_screenshots = _backend_runtime.state.screenshots_path
    original_monitor = _backend_runtime.state.monitor
    original_paths = dict(_backend_runtime.state.paths)
    original_running = _backend_runtime.state.is_running
    original_background_thread_status = dict(_backend_runtime.state.background_thread_status)

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            photos_path = tmp_path / "private-photos"
            screenshots_path = tmp_path / "private-screenshots"
            photos_path.mkdir()
            screenshots_path.mkdir()
            events = []

            def register_prefixes(prefixes):
                events.append(("register", prefixes))

            def record_print(*values, **_kwargs):
                message = " ".join(str(value) for value in values)
                if "[Storage]" in message:
                    events.append(("print", message))

            def create_monitor(*_args, **_kwargs):
                events.append(("monitor", None))
                return object()

            with (
                patch.object(
                    _backend_media,
                    "identify_logs_folder",
                    return_value=(str(photos_path), str(screenshots_path)),
                ),
                patch.object(
                    _backend_runtime,
                    "register_runtime_log_path_prefixes",
                    side_effect=register_prefixes,
                    create=True,
                ),
                patch.object(_backend_runtime, "Monitor", side_effect=create_monitor),
                patch.object(_backend_face, "prewarm_runtime_models"),
                patch.object(_backend_runtime, "_start_background_thread_once"),
                patch.object(_backend_runtime, "_mount_static_once"),
                patch.object(_backend_plots, "_get_plot_dir", return_value=tmp_path / "plots"),
                patch("builtins.print", side_effect=record_print),
            ):
                asyncio.run(_backend_runtime.startup_event())

            assert events[0] == (
                "register",
                {
                    "<PHOTOS_ROOT>": str(photos_path),
                    "<SCREENSHOTS_ROOT>": str(screenshots_path),
                },
            )
            assert [event[0] for event in events[:4]] == [
                "register",
                "print",
                "print",
                "monitor",
            ]
    finally:
        server.app.router.routes[:] = original_routes
        _backend_runtime.state.photos_path = original_photos
        _backend_runtime.state.screenshots_path = original_screenshots
        _backend_runtime.state.monitor = original_monitor
        _backend_runtime.state.paths = original_paths
        _backend_runtime.state.is_running = original_running
        _backend_runtime.state.background_thread_status = original_background_thread_status


def test_startup_event_is_idempotent_for_static_mounts_and_threads():
    original_routes = list(server.app.router.routes)
    original_photos = _backend_runtime.state.photos_path
    original_screenshots = _backend_runtime.state.screenshots_path
    original_monitor = _backend_runtime.state.monitor
    original_paths = dict(_backend_runtime.state.paths)
    original_background_thread_status = dict(_backend_runtime.state.background_thread_status)

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            photos_path = tmp_path / "photos"
            screenshots_path = tmp_path / "screenshots"
            photos_path.mkdir()
            screenshots_path.mkdir()

            _DummyThread.started_count = 0
            monitor_calls = []

            def create_monitor(*args, **kwargs):
                monitor_calls.append((args, kwargs))
                return object()

            with (
                patch.object(_backend_media, "identify_logs_folder", return_value=(str(photos_path), str(screenshots_path))),
                patch.object(_backend_media, "find_latest_file_recursive", return_value=None),
                patch.object(_backend_runtime, "Monitor", side_effect=create_monitor),
                patch.object(_backend_runtime.threading, "Thread", _DummyThread),
                patch.object(_backend_runtime.Config, "get_plot_dir", return_value=tmp_path / "plot_outputs"),
                patch.object(_backend_runtime.Config, "get_runtime_dir", return_value=tmp_path / "runtime"),
            ):
                asyncio.run(_backend_runtime.startup_event())
                after_first_startup = _static_route_directories()
                asyncio.run(_backend_runtime.startup_event())
                after_second_startup = _static_route_directories()

            assert after_first_startup == {
                "/static/photos": os.path.abspath(str(photos_path)),
                "/static/plots": os.path.abspath(str(tmp_path / "plot_outputs")),
                "/static/screenshots": os.path.abspath(str(screenshots_path)),
            }
            assert after_second_startup == after_first_startup
            assert _DummyThread.started_count == 7
            assert len(monitor_calls) == 2
            assert all(
                kwargs["state_path"] == tmp_path / "runtime" / "focus-presence-state.json"
                for _, kwargs in monitor_calls
            )
    finally:
        server.app.router.routes[:] = original_routes
        _backend_runtime.state.photos_path = original_photos
        _backend_runtime.state.screenshots_path = original_screenshots
        _backend_runtime.state.monitor = original_monitor
        _backend_runtime.state.paths = original_paths
        _backend_runtime.state.background_thread_status = original_background_thread_status


def test_startup_event_prewarms_runtime_models_before_background_threads():
    original_routes = list(server.app.router.routes)
    original_photos = _backend_runtime.state.photos_path
    original_screenshots = _backend_runtime.state.screenshots_path
    original_monitor = _backend_runtime.state.monitor
    original_paths = dict(_backend_runtime.state.paths)
    original_background_thread_status = dict(_backend_runtime.state.background_thread_status)

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
                patch.object(_backend_media, "identify_logs_folder", return_value=(str(photos_path), str(screenshots_path))),
                patch.object(_backend_media, "find_latest_file_recursive", return_value=None),
                patch.object(_backend_runtime, "Monitor", side_effect=lambda *args, **kwargs: object()),
                patch.object(_backend_face, "prewarm_runtime_models", side_effect=record_prewarm),
                patch.object(_backend_runtime.threading, "Thread", _RecordingThread),
                patch.object(_backend_runtime.Config, "get_plot_dir", return_value=tmp_path / "plot_outputs"),
            ):
                asyncio.run(_backend_runtime.startup_event())

            assert events[0] == "prewarm"
            assert any(event.startswith("thread:") for event in events[1:])
    finally:
        server.app.router.routes[:] = original_routes
        _backend_runtime.state.photos_path = original_photos
        _backend_runtime.state.screenshots_path = original_screenshots
        _backend_runtime.state.monitor = original_monitor
        _backend_runtime.state.paths = original_paths
        _backend_runtime.state.background_thread_status = original_background_thread_status


def test_startup_event_retries_partial_failure_without_duplicate_threads():
    original_routes = list(server.app.router.routes)
    original_photos = _backend_runtime.state.photos_path
    original_screenshots = _backend_runtime.state.screenshots_path
    original_monitor = _backend_runtime.state.monitor
    original_paths = dict(_backend_runtime.state.paths)
    original_running = _backend_runtime.state.is_running
    original_background_thread_status = dict(_backend_runtime.state.background_thread_status)

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
                patch.object(_backend_media, "identify_logs_folder", return_value=(str(photos_path), str(screenshots_path))),
                patch.object(_backend_media, "find_latest_file_recursive", side_effect=flaky_find_latest_file_recursive),
                patch.object(_backend_runtime, "Monitor", side_effect=lambda *args, **kwargs: object()),
                patch.object(_backend_runtime.threading, "Thread", _DummyThread),
                patch.object(_backend_runtime.Config, "get_plot_dir", return_value=tmp_path / "plot_outputs"),
            ):
                asyncio.run(_backend_runtime.startup_event())
                asyncio.run(_backend_runtime.startup_event())
                after_retry = _static_route_directories()

            assert after_retry == {
                "/static/photos": os.path.abspath(str(photos_path)),
                "/static/plots": os.path.abspath(str(tmp_path / "plot_outputs")),
                "/static/screenshots": os.path.abspath(str(screenshots_path)),
            }
            assert _DummyThread.started_count == 7
    finally:
        server.app.router.routes[:] = original_routes
        _backend_runtime.state.photos_path = original_photos
        _backend_runtime.state.screenshots_path = original_screenshots
        _backend_runtime.state.monitor = original_monitor
        _backend_runtime.state.paths = original_paths
        _backend_runtime.state.is_running = original_running
        _backend_runtime.state.background_thread_status = original_background_thread_status


def test_startup_event_updates_static_mounts_after_shutdown():
    original_routes = list(server.app.router.routes)
    original_photos = _backend_runtime.state.photos_path
    original_screenshots = _backend_runtime.state.screenshots_path
    original_monitor = _backend_runtime.state.monitor
    original_paths = dict(_backend_runtime.state.paths)
    original_running = _backend_runtime.state.is_running
    original_background_thread_status = dict(_backend_runtime.state.background_thread_status)

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
                    _backend_media,
                    "identify_logs_folder",
                    side_effect=[
                        (str(photos_path_1), str(screenshots_path_1)),
                        (str(photos_path_2), str(screenshots_path_2)),
                    ],
                ),
                patch.object(_backend_media, "find_latest_file_recursive", return_value=None),
                patch.object(_backend_runtime, "Monitor", side_effect=lambda *args, **kwargs: object()),
                patch.object(_backend_runtime.threading, "Thread", _DummyThread),
                patch.object(_backend_runtime.Config, "get_plot_dir", return_value=tmp_path / "plot_outputs"),
            ):
                asyncio.run(_backend_runtime.startup_event())
                first_mounts = _static_route_directories()
                asyncio.run(_backend_runtime.shutdown_event())
                asyncio.run(_backend_runtime.startup_event())
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
        _backend_runtime.state.photos_path = original_photos
        _backend_runtime.state.screenshots_path = original_screenshots
        _backend_runtime.state.monitor = original_monitor
        _backend_runtime.state.paths = original_paths
        _backend_runtime.state.is_running = original_running
        _backend_runtime.state.background_thread_status = original_background_thread_status


def test_startup_event_resumes_only_missing_threads_after_partial_start_failure():
    original_routes = list(server.app.router.routes)
    original_photos = _backend_runtime.state.photos_path
    original_screenshots = _backend_runtime.state.screenshots_path
    original_monitor = _backend_runtime.state.monitor
    original_paths = dict(_backend_runtime.state.paths)
    original_running = _backend_runtime.state.is_running
    original_background_thread_status = dict(_backend_runtime.state.background_thread_status)

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
                patch.object(_backend_media, "identify_logs_folder", return_value=(str(photos_path), str(screenshots_path))),
                patch.object(_backend_media, "find_latest_file_recursive", return_value=None),
                patch.object(_backend_runtime, "Monitor", side_effect=lambda *args, **kwargs: object()),
                patch.object(_backend_runtime.threading, "Thread", _PartiallyFailingThread),
                patch.object(_backend_runtime.Config, "get_plot_dir", return_value=tmp_path / "plot_outputs"),
            ):
                asyncio.run(_backend_runtime.startup_event())
                after_first_startup = dict(_PartiallyFailingThread.start_counts)
                asyncio.run(_backend_runtime.startup_event())
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
                "face_detection_loop": 1,
            }
            assert _static_route_directories() == {
                "/static/photos": os.path.abspath(str(photos_path)),
                "/static/plots": os.path.abspath(str(tmp_path / "plot_outputs")),
                "/static/screenshots": os.path.abspath(str(screenshots_path)),
            }
    finally:
        server.app.router.routes[:] = original_routes
        _backend_runtime.state.photos_path = original_photos
        _backend_runtime.state.screenshots_path = original_screenshots
        _backend_runtime.state.monitor = original_monitor
        _backend_runtime.state.paths = original_paths
        _backend_runtime.state.is_running = original_running
        _backend_runtime.state.background_thread_status = original_background_thread_status

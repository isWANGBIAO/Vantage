import asyncio
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src import server


class _DummyCamera:
    def __init__(self, opened):
        self._opened = opened

    def isOpened(self):
        return self._opened


class _DummyFrame:
    def copy(self):
        return self


class _FakeClock:
    def __init__(self):
        self.current = 0.0

    def monotonic(self):
        return self.current

    def sleep(self, seconds):
        self.current += max(0.0, seconds)


class _TimestampedFrame:
    def __init__(self, clock):
        self.clock = clock
        self.copy_times = []

    def copy(self):
        self.copy_times.append(self.clock.monotonic())
        return self


class _FlakyCopyFrame:
    def __init__(self):
        self.copy_count = 0

    def copy(self):
        self.copy_count += 1
        if self.copy_count == 1:
            raise RuntimeError("frame copy unavailable")
        return self


class FaceLiveEndpointTests(unittest.TestCase):
    def setUp(self):
        self.original_points = getattr(server.state, "live_face_points", None)
        self.original_camera = server.state.camera
        self.original_latest_frame = getattr(server.state, "latest_frame", None)
        self.original_latest_frame_published_at = getattr(
            server.state,
            "latest_frame_published_at",
            None,
        )
        self.original_latest_live_face_score = getattr(server.state, "latest_live_face_score", None)
        self.original_face_live_last_seen_at = getattr(server.state, "face_live_last_seen_at", None)
        self.original_show_person_box = getattr(server.state, "show_person_box", None)
        self.original_person_boxes = getattr(server.state, "person_boxes", None)
        self.original_video_stream_client_count = getattr(server.state, "video_stream_client_count", None)
        self.original_paths_object = server.state.paths
        self.original_paths = dict(server.state.paths)
        self.original_photos_path = server.state.photos_path
        self.original_is_running = server.state.is_running

    def _restore_paths_in_place(self):
        self.assertIs(server.state.paths, self.original_paths_object)
        server.state.paths.clear()
        server.state.paths.update(self.original_paths)

    def tearDown(self):
        server.state.live_face_points = [] if self.original_points is None else self.original_points
        server.state.camera = self.original_camera
        server.state.latest_frame = self.original_latest_frame
        server.state.latest_frame_published_at = self.original_latest_frame_published_at
        server.state.latest_live_face_score = self.original_latest_live_face_score
        server.state.face_live_last_seen_at = self.original_face_live_last_seen_at
        server.state.show_person_box = self.original_show_person_box
        server.state.person_boxes = [] if self.original_person_boxes is None else self.original_person_boxes
        if self.original_video_stream_client_count is None and hasattr(server.state, "video_stream_client_count"):
            delattr(server.state, "video_stream_client_count")
        else:
            server.state.video_stream_client_count = self.original_video_stream_client_count
        self._restore_paths_in_place()
        server.state.photos_path = self.original_photos_path
        server.state.is_running = self.original_is_running

    def test_path_restore_preserves_existing_monitor_alias(self):
        monitor_paths_alias = server.state.paths
        server.state.paths["photo"] = "temporary-photo.jpg"

        self._restore_paths_in_place()

        self.assertIs(server.state.paths, monitor_paths_alias)
        self.assertEqual(server.state.paths, self.original_paths)

    def test_store_live_face_result_keeps_only_passing_points_within_window(self):
        server.state.live_face_points = []

        with patch.object(server, "FACE_LIVE_WINDOW_SECONDS", 60):
            server.store_live_face_result(
                {
                    "passed": False,
                    "timestamp": 100.0,
                    "datetime": "2026-03-14 21:00:00",
                    "score": 22.0,
                }
            )
            server.store_live_face_result(
                {
                    "passed": True,
                    "timestamp": 100.0,
                    "datetime": "2026-03-14 21:00:00",
                    "score": 22.0,
                }
            )
            server.store_live_face_result(
                {
                    "passed": True,
                    "timestamp": 170.0,
                    "datetime": "2026-03-14 21:01:10",
                    "score": 31.5,
                }
            )

            points = server.snapshot_live_face_points(now_ts=170.0)

        self.assertEqual(points, [{"timestamp": 170.0, "datetime": "2026-03-14 21:01:10", "score": 31.5}])

    def test_get_face_live_returns_latest_realtime_score_payload(self):
        server.state.camera = _DummyCamera(True)
        server.state.live_face_points = [
            {"timestamp": 171.0, "datetime": "2026-03-14 21:01:11", "score": 29.8},
            {"timestamp": 172.0, "datetime": "2026-03-14 21:01:12", "score": 30.2},
        ]

        with patch.object(server.time, "time", return_value=172.0):
            payload = asyncio.run(server.get_face_live())

        self.assertTrue(payload["camera_online"])
        self.assertEqual(payload["latest_score"], 30.2)
        self.assertEqual(payload["latest_datetime"], "2026-03-14 21:01:12")
        self.assertEqual(len(payload["points"]), 2)

    def test_get_face_live_returns_empty_points_when_camera_is_offline(self):
        server.state.camera = _DummyCamera(False)
        server.state.live_face_points = [{"timestamp": 172.0, "datetime": "2026-03-14 21:01:12", "score": 30.2}]

        payload = asyncio.run(server.get_face_live())

        self.assertFalse(payload["camera_online"])
        self.assertEqual(payload["points"], [])
        self.assertIsNone(payload["latest_score"])
        self.assertEqual(payload["latest_datetime"], "")

    def test_live_inference_intervals_are_one_second(self):
        self.assertEqual(server.FACE_LIVE_SAMPLE_INTERVAL_SECONDS, 1.0)
        self.assertEqual(server.FACE_DETECTION_SAMPLE_INTERVAL_SECONDS, 1.0)

    def test_face_live_viewer_activity_expires_without_visible_polling(self):
        server.mark_face_live_viewer_active(now_ts=100.0)

        self.assertTrue(server.has_active_face_live_viewer(now_ts=102.0))
        self.assertFalse(server.has_active_face_live_viewer(now_ts=110.0))

    def test_face_live_analysis_remains_eligible_without_visible_viewer(self):
        server.state.face_live_last_seen_at = 0.0

        with patch.object(
            server,
            "load_background_mode",
            return_value="balanced",
            create=True,
        ):
            self.assertTrue(server.should_run_face_live_analysis(now_ts=100.0))

    def test_get_face_live_only_marks_viewer_active_when_requested(self):
        server.state.camera = _DummyCamera(True)
        server.state.face_live_last_seen_at = 0.0

        asyncio.run(server.get_face_live(active=False))
        self.assertEqual(server.state.face_live_last_seen_at, 0.0)

        with patch.object(server.time, "time", return_value=123.0):
            asyncio.run(server.get_face_live(active=True))

        self.assertEqual(server.state.face_live_last_seen_at, 123.0)

    def test_face_detection_runs_independently_of_enabled_boxes(self):
        server.state.show_person_box = True
        server.state.video_stream_client_count = 0

        self.assertTrue(server.should_run_face_detection())

        server.state.show_person_box = False
        self.assertTrue(server.should_run_face_detection())

    def test_toggle_detection_clears_boxes_without_stopping_detection(self):
        server.state.show_person_box = True
        server.state.person_boxes = [(1, 2, 3, 4)]

        payload = asyncio.run(server.toggle_detection())

        self.assertEqual(
            payload,
            {"status": "success", "show_person_box": False},
        )
        self.assertFalse(server.state.show_person_box)
        self.assertEqual(server.state.person_boxes, [])
        self.assertTrue(server.should_run_face_detection())

    def test_runtime_inference_has_no_background_mode_helpers(self):
        self.assertFalse(hasattr(server, "load_background_mode"))
        self.assertFalse(hasattr(server, "sanitize_background_mode"))
        self.assertFalse(hasattr(server, "_background_mode_cache"))

    def test_face_live_loop_caps_consecutive_inference_starts_at_one_hertz(self):
        clock = _FakeClock()
        inference_starts = []
        frame = _TimestampedFrame(clock)
        server.state.is_running = True
        server.state.latest_frame = frame

        def analyze(*_args, **_kwargs):
            inference_starts.append(clock.monotonic())
            if len(inference_starts) == 3:
                server.state.is_running = False
            return {"passed": False}

        pipeline = SimpleNamespace(analyze_image_data=analyze)
        with (
            patch.object(server, "should_run_face_live_analysis", return_value=True),
            patch.object(server, "get_face_analysis_runtime", return_value=(object(), object(), object())),
            patch.object(server, "get_face_analysis_pipeline_module", return_value=pipeline),
            patch.object(server.time, "monotonic", side_effect=clock.monotonic),
            patch.object(server.time, "sleep", side_effect=clock.sleep),
            patch("builtins.print"),
        ):
            server.face_live_loop()

        self.assertEqual(len(inference_starts), 3)
        self.assertEqual(frame.copy_times, inference_starts)
        self.assertTrue(
            all(
                later - earlier >= 1.0
                for earlier, later in zip(inference_starts, inference_starts[1:])
            )
        )

    def test_face_live_lazy_runtime_delay_does_not_collapse_actual_start_gap(self):
        clock = _FakeClock()
        inference_starts = []
        runtime_loads = 0
        server.state.is_running = True
        server.state.latest_frame = _DummyFrame()

        def get_runtime():
            nonlocal runtime_loads
            runtime_loads += 1
            if runtime_loads == 1:
                clock.sleep(2.0)
            return object(), object(), object()

        def analyze(*_args, **_kwargs):
            inference_starts.append(clock.monotonic())
            if len(inference_starts) == 2:
                server.state.is_running = False
            return {"passed": False}

        pipeline = SimpleNamespace(analyze_image_data=analyze)
        with (
            patch.object(server, "get_face_analysis_runtime", side_effect=get_runtime),
            patch.object(server, "get_face_analysis_pipeline_module", return_value=pipeline),
            patch.object(server.time, "monotonic", side_effect=clock.monotonic),
            patch.object(server.time, "sleep", side_effect=clock.sleep),
            patch("builtins.print"),
        ):
            server.face_live_loop()

        self.assertEqual(inference_starts, [2.0, 3.0])

    def test_face_live_runtime_preparation_failures_do_not_busy_spin(self):
        clock = _FakeClock()
        preparation_attempts = []
        server.state.is_running = True
        server.state.latest_frame = _DummyFrame()

        def fail_runtime_preparation():
            preparation_attempts.append(clock.monotonic())
            if len(preparation_attempts) == 3:
                server.state.is_running = False
            raise RuntimeError("runtime unavailable")

        with (
            patch.object(server, "get_face_analysis_runtime", side_effect=fail_runtime_preparation),
            patch.object(server.time, "monotonic", side_effect=clock.monotonic),
            patch.object(server.time, "sleep", side_effect=clock.sleep),
            patch("builtins.print"),
        ):
            server.face_live_loop()

        self.assertEqual(preparation_attempts, [0.0, 1.0, 2.0])

    def test_face_detection_loop_caps_consecutive_inference_starts_at_one_hertz(self):
        clock = _FakeClock()
        inference_starts = []
        frame = _TimestampedFrame(clock)
        server.state.is_running = True
        server.state.show_person_box = True
        server.state.latest_frame = frame
        server.state.latest_frame_published_at = 0.0

        def detect(*_args, **_kwargs):
            inference_starts.append(clock.monotonic())
            if len(inference_starts) == 3:
                server.state.is_running = False
            return []

        with (
            patch.object(server, "get_face_detector", return_value=object()),
            patch.object(server, "should_run_face_detection", return_value=True),
            patch.object(server, "detect_foreground_presence_face_boxes", side_effect=detect),
            patch.object(server.time, "monotonic", side_effect=clock.monotonic),
            patch.object(server.time, "sleep", side_effect=clock.sleep),
            patch("builtins.print"),
        ):
            server.face_detection_loop()

        self.assertEqual(len(inference_starts), 3)
        self.assertEqual(frame.copy_times, inference_starts)
        self.assertTrue(
            all(
                later - earlier >= 1.0
                for earlier, later in zip(inference_starts, inference_starts[1:])
            )
        )

    def test_blocking_photo_save_does_not_delay_later_inference_starts(self):
        from src.manager.take_photo.take_a_photo import (
            PresencePhotoSaveCoordinator,
        )

        frame = _DummyFrame()
        save_started = threading.Event()
        release_save = threading.Event()
        third_inference = threading.Event()
        detector_calls = 0
        server.state.is_running = True
        server.state.show_person_box = True
        server.state.latest_frame = frame
        server.state.latest_frame_published_at = 0.0
        server.state.photos_path = "photos"
        server.state.paths["photo"] = None

        def blocking_save(*_args, **_kwargs):
            save_started.set()
            release_save.wait(timeout=2)
            return "async-presence-photo.jpg"

        coordinator = PresencePhotoSaveCoordinator(save_fn=blocking_save)

        def wait_for_slot(*_args, **_kwargs):
            with server.state.lock:
                server.state.latest_frame_published_at = float(detector_calls)
            return float(detector_calls)

        def detect(*_args, **_kwargs):
            nonlocal detector_calls
            detector_calls += 1
            if detector_calls == 3:
                server.state.is_running = False
                third_inference.set()
            return [(1, 2, 3, 4)]

        loop_thread = threading.Thread(target=server.face_detection_loop)
        try:
            with (
                patch.object(server, "get_face_detector", return_value=object()),
                patch.object(
                    server,
                    "wait_for_next_inference_start",
                    side_effect=wait_for_slot,
                ),
                patch.object(
                    server,
                    "detect_foreground_presence_face_boxes",
                    side_effect=detect,
                ),
                patch.object(
                    server,
                    "_presence_photo_save_coordinator",
                    coordinator,
                    create=True,
                ),
                patch("builtins.print"),
            ):
                loop_thread.start()
                self.assertTrue(save_started.wait(timeout=1))
                self.assertTrue(third_inference.wait(timeout=0.5))
        finally:
            server.state.is_running = False
            release_save.set()
            loop_thread.join(timeout=2)
            self.assertTrue(coordinator.close(timeout=2))

        deadline = time.monotonic() + 1
        while (
            server.state.paths["photo"] != "async-presence-photo.jpg"
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)

        self.assertFalse(loop_thread.is_alive())
        self.assertEqual(detector_calls, 3)
        self.assertEqual(
            server.state.paths["photo"],
            "async-presence-photo.jpg",
        )

    def test_face_detection_model_load_delay_keeps_actual_start_gap(self):
        clock = _FakeClock()
        inference_starts = []
        server.state.is_running = True
        server.state.show_person_box = True
        server.state.latest_frame = _DummyFrame()
        server.state.latest_frame_published_at = 0.0

        def load_detector():
            clock.sleep(2.0)
            return object()

        def detect(*_args, **_kwargs):
            inference_starts.append(clock.monotonic())
            if len(inference_starts) == 2:
                server.state.is_running = False
            return []

        with (
            patch.object(server, "get_face_detector", side_effect=load_detector),
            patch.object(server, "detect_foreground_presence_face_boxes", side_effect=detect),
            patch.object(server.time, "monotonic", side_effect=clock.monotonic),
            patch.object(server.time, "sleep", side_effect=clock.sleep),
            patch("builtins.print"),
        ):
            server.face_detection_loop()

        self.assertEqual(inference_starts, [2.0, 3.0])

    def test_frame_disappearing_during_wait_does_not_consume_inference_slot(self):
        clock = _FakeClock()
        detector = Mock(return_value=[])
        wait_baselines = []
        server.state.is_running = True
        server.state.show_person_box = True
        server.state.latest_frame = _DummyFrame()
        server.state.latest_frame_published_at = 0.0

        def wait_for_slot(last_started_at, *_args, **_kwargs):
            wait_baselines.append(last_started_at)
            if len(wait_baselines) == 1:
                with server.state.lock:
                    server.state.latest_frame = None
                    server.state.latest_frame_published_at = None
            return clock.monotonic()

        def idle_sleep(seconds):
            clock.sleep(seconds)
            with server.state.lock:
                server.state.latest_frame = _DummyFrame()
                server.state.latest_frame_published_at = clock.monotonic()

        def detect(*_args, **_kwargs):
            server.state.is_running = False
            return []

        detector.side_effect = detect
        with (
            patch.object(server, "get_face_detector", return_value=object()),
            patch.object(server, "wait_for_next_inference_start", side_effect=wait_for_slot),
            patch.object(server, "detect_foreground_presence_face_boxes", detector),
            patch.object(server.time, "sleep", side_effect=idle_sleep),
            patch("builtins.print"),
        ):
            server.face_detection_loop()

        self.assertEqual(wait_baselines, [None, None])
        self.assertEqual(detector.call_count, 1)

    def test_frame_copy_failure_does_not_stop_later_fresh_detection(self):
        frame = _FlakyCopyFrame()
        detector = Mock()
        server.state.is_running = True
        server.state.show_person_box = True
        server.state.latest_frame = frame
        server.state.latest_frame_published_at = 0.0
        server.state.person_boxes = [(1, 2, 3, 4)]

        def idle_sleep(_seconds):
            with server.state.lock:
                server.state.latest_frame_published_at = 1.0

        def detect(*_args, **_kwargs):
            server.state.is_running = False
            return []

        detector.side_effect = detect
        with (
            patch.object(server, "get_face_detector", return_value=object()),
            patch.object(
                server,
                "wait_for_next_inference_start",
                side_effect=[0.0, 1.0],
            ),
            patch.object(
                server,
                "detect_foreground_presence_face_boxes",
                detector,
            ),
            patch.object(
                server._presence_photo_save_coordinator,
                "submit",
            ) as submit_photo,
            patch.object(server.time, "sleep", side_effect=idle_sleep),
            patch("builtins.print"),
        ):
            server.face_detection_loop()

        self.assertEqual(frame.copy_count, 2)
        self.assertEqual(detector.call_count, 1)
        submit_photo.assert_not_called()
        self.assertEqual(server.state.person_boxes, [])

    def test_disabling_boxes_during_rate_limit_wait_keeps_inference_running(self):
        detector = Mock(return_value=[])
        wait_count = 0
        server.state.is_running = True
        server.state.show_person_box = True
        server.state.latest_frame = _DummyFrame()
        server.state.latest_frame_published_at = 0.0
        server.state.person_boxes = [(1, 2, 3, 4)]

        def wait_for_slot(*_args, **_kwargs):
            nonlocal wait_count
            wait_count += 1
            if wait_count == 2:
                with server.state.lock:
                    server.state.show_person_box = False
                    server.state.person_boxes = []
            return float(wait_count - 1)

        def detect(*_args, **_kwargs):
            if detector.call_count == 2:
                server.state.is_running = False
            return []

        with (
            patch.object(server, "get_face_detector", return_value=object()),
            patch.object(server, "wait_for_next_inference_start", side_effect=wait_for_slot),
            patch.object(
                server,
                "detect_foreground_presence_face_boxes",
                side_effect=detect,
            ) as detector,
            patch.object(server.time, "monotonic", side_effect=[0.0, 1.0]),
            patch("builtins.print"),
        ):
            server.face_detection_loop()

        self.assertEqual(detector.call_count, 2)
        self.assertEqual(server.state.person_boxes, [])

    def test_hidden_overlay_still_saves_detected_original_frame(self):
        frame = _DummyFrame()
        saved_path = "presence-photo.jpg"
        server.state.is_running = True
        server.state.show_person_box = False
        server.state.latest_frame = frame
        server.state.latest_frame_published_at = 10.0
        server.state.photos_path = "photos"
        server.state.paths["photo"] = None

        def detect(*_args, **_kwargs):
            server.state.is_running = False
            return [(1, 2, 3, 4)]

        with (
            patch.object(server, "get_face_detector", return_value=object()),
            patch.object(
                server,
                "detect_foreground_presence_face_boxes",
                side_effect=detect,
            ),
            patch.object(
                server._presence_photo_save_coordinator,
                "submit",
                side_effect=lambda *_args, **kwargs: (
                    kwargs["on_success"](saved_path),
                    True,
                )[1],
            ) as submit_photo,
            patch.object(server, "get_location", create=True) as get_location,
            patch.object(server.time, "monotonic", return_value=10.0),
            patch("builtins.print"),
        ):
            server.face_detection_loop()

        self.assertIs(submit_photo.call_args.args[0], frame)
        self.assertEqual(submit_photo.call_args.args[1], "photos")
        self.assertIs(
            submit_photo.call_args.kwargs["location_provider"],
            get_location,
        )
        self.assertEqual(server.state.paths["photo"], saved_path)
        self.assertEqual(server.state.person_boxes, [])

    def test_face_detection_without_foreground_face_does_not_save(self):
        server.state.is_running = True
        server.state.show_person_box = True
        server.state.latest_frame = _DummyFrame()
        server.state.latest_frame_published_at = 10.0
        server.state.photos_path = "photos"

        def detect(*_args, **_kwargs):
            server.state.is_running = False
            return []

        with (
            patch.object(server, "get_face_detector", return_value=object()),
            patch.object(
                server,
                "detect_foreground_presence_face_boxes",
                side_effect=detect,
            ),
            patch.object(
                server._presence_photo_save_coordinator,
                "submit",
            ) as submit_photo,
            patch.object(server.time, "monotonic", return_value=10.0),
            patch("builtins.print"),
        ):
            server.face_detection_loop()

        submit_photo.assert_not_called()
        self.assertEqual(server.state.person_boxes, [])

    def test_first_presence_after_59_empty_samples_saves_immediately(self):
        sample_count = 0
        server.state.is_running = True
        server.state.show_person_box = True
        server.state.latest_frame = _DummyFrame()
        server.state.latest_frame_published_at = 0.0
        server.state.photos_path = "photos"
        server.state.paths["photo"] = None

        def wait_for_slot(*_args, **_kwargs):
            next_sample = float(sample_count + 1)
            with server.state.lock:
                server.state.latest_frame_published_at = next_sample
            return next_sample

        def detect(*_args, **_kwargs):
            nonlocal sample_count
            sample_count += 1
            if sample_count < 60:
                return []
            server.state.is_running = False
            return [(1, 2, 3, 4)]

        with (
            patch.object(server, "get_face_detector", return_value=object()),
            patch.object(
                server,
                "wait_for_next_inference_start",
                side_effect=wait_for_slot,
            ),
            patch.object(
                server,
                "detect_foreground_presence_face_boxes",
                side_effect=detect,
            ),
            patch.object(
                server._presence_photo_save_coordinator,
                "submit",
                side_effect=lambda *_args, **kwargs: (
                    kwargs["on_success"]("presence-photo.jpg"),
                    True,
                )[1],
            ) as submit_photo,
            patch.object(server, "get_location", create=True),
            patch("builtins.print"),
        ):
            server.face_detection_loop()

        self.assertEqual(sample_count, 60)
        submit_photo.assert_called_once()
        self.assertEqual(server.state.paths["photo"], "presence-photo.jpg")

    def test_stale_retained_frame_is_not_detected_or_saved(self):
        server.state.is_running = True
        server.state.show_person_box = True
        server.state.latest_frame = _DummyFrame()
        server.state.latest_frame_published_at = 1.0
        server.state.photos_path = "photos"
        server.state.person_boxes = [(1, 2, 3, 4)]

        def stop_loop(_seconds):
            server.state.is_running = False

        with (
            patch.object(server, "get_face_detector", return_value=object()),
            patch.object(
                server,
                "detect_foreground_presence_face_boxes",
            ) as detect,
            patch.object(
                server._presence_photo_save_coordinator,
                "submit",
            ) as submit_photo,
            patch.object(server.time, "monotonic", return_value=10.0),
            patch.object(server.time, "sleep", side_effect=stop_loop),
            patch("builtins.print"),
        ):
            server.face_detection_loop()

        detect.assert_not_called()
        submit_photo.assert_not_called()
        self.assertEqual(server.state.person_boxes, [])

    def test_same_frozen_frame_is_not_saved_again_across_minute_boundary(self):
        detector_calls = 0
        server.state.is_running = True
        server.state.show_person_box = True
        server.state.latest_frame = _DummyFrame()
        server.state.latest_frame_published_at = 58.0
        server.state.photos_path = "photos"

        def detect(*_args, **_kwargs):
            nonlocal detector_calls
            detector_calls += 1
            if detector_calls == 2:
                server.state.is_running = False
            return [(1, 2, 3, 4)]

        with (
            patch.object(server, "get_face_detector", return_value=object()),
            patch.object(
                server,
                "wait_for_next_inference_start",
                side_effect=[59.0, 60.0],
            ),
            patch.object(
                server,
                "detect_foreground_presence_face_boxes",
                side_effect=detect,
            ),
            patch.object(
                server._presence_photo_save_coordinator,
                "submit",
                return_value=True,
            ) as submit_photo,
            patch.object(server, "get_location", create=True),
            patch("builtins.print"),
        ):
            server.face_detection_loop()

        self.assertEqual(detector_calls, 2)
        submit_photo.assert_called_once()

    def test_face_detection_model_failure_does_not_save_or_publish_box(self):
        server.state.is_running = True
        server.state.show_person_box = True
        server.state.latest_frame = _DummyFrame()
        server.state.latest_frame_published_at = 10.0
        server.state.photos_path = "photos"
        server.state.person_boxes = [(1, 2, 3, 4)]

        def fail_detection(*_args, **_kwargs):
            server.state.is_running = False
            raise RuntimeError("model unavailable")

        with (
            patch.object(server, "get_face_detector", return_value=object()),
            patch.object(
                server,
                "detect_foreground_presence_face_boxes",
                side_effect=fail_detection,
            ),
            patch.object(
                server._presence_photo_save_coordinator,
                "submit",
            ) as submit_photo,
            patch.object(server.time, "monotonic", return_value=10.0),
            patch("builtins.print"),
        ):
            server.face_detection_loop()

        submit_photo.assert_not_called()
        self.assertEqual(server.state.person_boxes, [])

    def test_face_detector_load_failure_retries_and_later_detects(self):
        server.state.is_running = True
        server.state.latest_frame = _DummyFrame()
        server.state.latest_frame_published_at = 0.0
        server.state.person_boxes = [(1, 2, 3, 4)]
        detector = object()
        load_attempts = 0
        boxes_before_retry = None

        def load_detector():
            nonlocal load_attempts, boxes_before_retry
            load_attempts += 1
            if load_attempts == 1:
                raise RuntimeError("model unavailable")
            boxes_before_retry = list(server.state.person_boxes)
            return detector

        def detect(*_args, **_kwargs):
            server.state.is_running = False
            return []

        with (
            patch.object(
                server,
                "get_face_detector",
                side_effect=load_detector,
            ) as get_detector_mock,
            patch.object(
                server,
                "detect_foreground_presence_face_boxes",
                side_effect=detect,
            ) as detect_presence,
            patch.object(server.time, "monotonic", return_value=0.0),
            patch.object(server.time, "sleep") as sleep,
            patch("builtins.print"),
        ):
            server.face_detection_loop()

        self.assertEqual(get_detector_mock.call_count, 2)
        sleep.assert_called_once_with(1.0)
        self.assertEqual(boxes_before_retry, [])
        self.assertIs(detect_presence.call_args.kwargs["model"], detector)
        self.assertEqual(server.state.person_boxes, [])

    def test_missing_camera_frame_clears_previous_visible_box(self):
        server.state.is_running = True
        server.state.latest_frame = None
        server.state.latest_frame_published_at = None
        server.state.person_boxes = [(1, 2, 3, 4)]

        def stop_loop(_seconds):
            server.state.is_running = False

        with (
            patch.object(server, "get_face_detector", return_value=object()),
            patch.object(server.time, "sleep", side_effect=stop_loop),
            patch("builtins.print"),
        ):
            server.face_detection_loop()

        self.assertEqual(server.state.person_boxes, [])

    def test_presence_photo_storage_failure_keeps_detected_box_and_old_path(self):
        server.state.is_running = True
        server.state.show_person_box = True
        server.state.latest_frame = _DummyFrame()
        server.state.latest_frame_published_at = 10.0
        server.state.photos_path = "photos"
        server.state.person_boxes = [(1, 2, 3, 4)]
        server.state.paths["photo"] = "old-photo.jpg"

        def detect(*_args, **_kwargs):
            server.state.is_running = False
            return [(5, 6, 7, 8)]

        def reject_save(*_args, **kwargs):
            kwargs["on_failure"](OSError("disk unavailable"))
            return True

        with (
            patch.object(server, "get_face_detector", return_value=object()),
            patch.object(
                server,
                "detect_foreground_presence_face_boxes",
                side_effect=detect,
            ),
            patch.object(
                server._presence_photo_save_coordinator,
                "submit",
                side_effect=reject_save,
            ),
            patch.object(server, "get_location", create=True),
            patch.object(server.time, "monotonic", return_value=10.0),
            patch("builtins.print"),
        ):
            server.face_detection_loop()

        self.assertEqual(server.state.person_boxes, [(5, 6, 7, 8)])
        self.assertEqual(server.state.paths["photo"], "old-photo.jpg")

    def test_presence_photo_storage_failure_retries_on_next_fresh_sample(self):
        detector_calls = 0
        boxes_seen_before_retry = None
        server.state.is_running = True
        server.state.show_person_box = True
        server.state.latest_frame = _DummyFrame()
        server.state.latest_frame_published_at = 10.0
        server.state.photos_path = "photos"
        server.state.paths["photo"] = "old-photo.jpg"

        def wait_for_slot(*_args, **_kwargs):
            next_sample = 10.0 + detector_calls
            with server.state.lock:
                server.state.latest_frame_published_at = next_sample
            return next_sample

        def detect(*_args, **_kwargs):
            nonlocal detector_calls, boxes_seen_before_retry
            detector_calls += 1
            if detector_calls == 2:
                boxes_seen_before_retry = list(server.state.person_boxes)
                server.state.is_running = False
            return [(5, 6, 7, 8)]

        submit_attempts = 0

        def submit_photo(*_args, **kwargs):
            nonlocal submit_attempts
            submit_attempts += 1
            if submit_attempts == 1:
                kwargs["on_failure"](OSError("disk unavailable"))
            else:
                kwargs["on_success"]("new-photo.jpg")
            return True

        with (
            patch.object(server, "get_face_detector", return_value=object()),
            patch.object(
                server,
                "wait_for_next_inference_start",
                side_effect=wait_for_slot,
            ),
            patch.object(
                server,
                "detect_foreground_presence_face_boxes",
                side_effect=detect,
            ),
            patch.object(
                server._presence_photo_save_coordinator,
                "submit",
                side_effect=submit_photo,
            ) as submit_photo_mock,
            patch.object(server, "get_location", create=True),
            patch("builtins.print"),
        ):
            server.face_detection_loop()

        self.assertEqual(boxes_seen_before_retry, [(5, 6, 7, 8)])
        self.assertEqual(submit_photo_mock.call_count, 2)
        self.assertEqual(server.state.paths["photo"], "new-photo.jpg")

    def test_presence_photo_location_failure_keeps_detected_box_and_old_path(self):
        server.state.is_running = True
        server.state.show_person_box = True
        server.state.latest_frame = _DummyFrame()
        server.state.latest_frame_published_at = 10.0
        server.state.photos_path = "photos"
        server.state.person_boxes = [(1, 2, 3, 4)]
        server.state.paths["photo"] = "old-photo.jpg"

        def detect(*_args, **_kwargs):
            server.state.is_running = False
            return [(5, 6, 7, 8)]

        def reject_location(*_args, **kwargs):
            try:
                kwargs["location_provider"]()
            except Exception as exc:
                kwargs["on_failure"](exc)
            return True

        with (
            patch.object(server, "get_face_detector", return_value=object()),
            patch.object(
                server,
                "detect_foreground_presence_face_boxes",
                side_effect=detect,
            ),
            patch.object(
                server._presence_photo_save_coordinator,
                "submit",
                side_effect=reject_location,
            ),
            patch.object(
                server,
                "get_location",
                side_effect=RuntimeError("location unavailable"),
                create=True,
            ),
            patch.object(server.time, "monotonic", return_value=10.0),
            patch("builtins.print"),
        ):
            server.face_detection_loop()

        self.assertEqual(server.state.person_boxes, [(5, 6, 7, 8)])
        self.assertEqual(server.state.paths["photo"], "old-photo.jpg")

    def test_video_stream_client_count_never_goes_below_zero(self):
        server.state.video_stream_client_count = 0

        server.unregister_video_stream_client()
        self.assertEqual(server.state.video_stream_client_count, 0)

        server.register_video_stream_client()
        server.register_video_stream_client()
        self.assertEqual(server.state.video_stream_client_count, 2)

        server.unregister_video_stream_client()
        self.assertEqual(server.state.video_stream_client_count, 1)

    def test_generate_frames_registers_and_unregisters_video_stream_client(self):
        server.state.video_stream_client_count = 0
        server.state.latest_frame = None

        frame_generator = server.generate_frames()
        self.assertEqual(server.state.video_stream_client_count, 0)

        first_frame = next(frame_generator)
        self.assertIn(b"Content-Type: image/jpeg", first_frame)
        self.assertEqual(server.state.video_stream_client_count, 1)

        frame_generator.close()
        self.assertEqual(server.state.video_stream_client_count, 0)

    def test_format_live_face_score_label_formats_numeric_and_missing(self):
        self.assertEqual(server.format_live_face_score_label(31.234), "Dark Circle Score: 31.23")
        self.assertEqual(server.format_live_face_score_label(None), "Dark Circle Score: --")

    def test_update_live_face_overlay_state_tracks_current_score(self):
        server.state.latest_live_face_score = 12.3

        server.update_live_face_overlay_state({"passed": False, "score": None})
        self.assertIsNone(server.state.latest_live_face_score)

        server.update_live_face_overlay_state({"passed": True, "score": 29.875})
        self.assertEqual(server.state.latest_live_face_score, 29.875)

    def test_live_overlay_fonts_are_double_the_previous_score_size(self):
        self.assertEqual(server.FACE_OVERLAY_BASE_SCORE_FONT_SCALE, 1.9)
        self.assertEqual(server.FACE_OVERLAY_SCORE_FONT_SCALE, 3.8)
        self.assertEqual(server.FACE_OVERLAY_PERSON_FONT_SCALE, 3.8)


if __name__ == "__main__":
    unittest.main()

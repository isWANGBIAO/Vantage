import asyncio
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from src.backend import camera as _backend_camera
from src.backend import runtime as _backend_runtime
from src.backend import system as _backend_system


class _FakeRequest:
    def __init__(self, body, headers):
        self._body = body
        self.headers = headers

    async def body(self):
        return self._body


class _OpenPhysicalCapture:
    def __init__(self, on_read=None):
        self.on_read = on_read
        self.release_count = 0

    def isOpened(self):
        return True

    def read(self):
        return self.on_read()

    def release(self):
        self.release_count += 1


class RendererCameraFrameTests(unittest.TestCase):
    def setUp(self):
        self.original_camera = _backend_runtime.state.camera
        self.original_renderer_camera = getattr(_backend_runtime.state, "renderer_camera", None)
        self.original_renderer_frame = getattr(_backend_runtime.state, "renderer_camera_frame", None)
        self.original_renderer_last_seen_at = getattr(_backend_runtime.state, "renderer_camera_last_seen_at", None)
        self.original_latest_frame = getattr(_backend_runtime.state, "latest_frame", None)
        self.original_latest_frame_published_at = getattr(
            _backend_runtime.state,
            "latest_frame_published_at",
            None,
        )
        self.original_is_running = _backend_runtime.state.is_running
        self.original_release_queue = list(_backend_runtime.state.camera_release_queue)
        self.original_release_ids = set(_backend_runtime.state.camera_release_ids)

    def tearDown(self):
        _backend_runtime.state.camera = self.original_camera
        _backend_runtime.state.renderer_camera = self.original_renderer_camera
        _backend_runtime.state.renderer_camera_frame = self.original_renderer_frame
        _backend_runtime.state.renderer_camera_last_seen_at = self.original_renderer_last_seen_at
        _backend_runtime.state.latest_frame = self.original_latest_frame
        _backend_runtime.state.latest_frame_published_at = self.original_latest_frame_published_at
        _backend_runtime.state.is_running = self.original_is_running
        _backend_runtime.state.camera_release_queue = self.original_release_queue
        _backend_runtime.state.camera_release_ids = self.original_release_ids

    def test_renderer_camera_frame_updates_backend_camera_state(self):
        frame = np.full((6, 8, 3), 127, dtype=np.uint8)
        ok, encoded = _backend_camera.cv2.imencode(".jpg", frame)
        self.assertTrue(ok)
        published_at = time.monotonic()

        with patch.object(_backend_camera.time, "monotonic", return_value=published_at):
            payload = asyncio.run(
                _backend_camera.receive_renderer_camera_frame(
                    _FakeRequest(
                        encoded.tobytes(),
                        {
                            "content-type": "image/jpeg",
                            "x-vantage-intent": _backend_camera.RENDERER_CAMERA_FRAME_INTENT,
                        },
                    )
                )
            )

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["camera_online"])
        self.assertEqual(payload["width"], 8)
        self.assertEqual(payload["height"], 6)
        self.assertTrue(_backend_camera._camera_online())
        self.assertIs(_backend_runtime.state.camera, _backend_runtime.state.renderer_camera)

        success, captured = _backend_runtime.state.camera.read()
        self.assertTrue(success)
        self.assertEqual(captured.shape, (6, 8, 3))
        self.assertEqual(_backend_runtime.state.latest_frame.shape, (6, 8, 3))
        self.assertEqual(_backend_runtime.state.renderer_camera_last_seen_at, published_at)
        self.assertEqual(_backend_runtime.state.latest_frame_published_at, published_at)

    def test_renderer_liveness_ignores_wall_clock_jumps(self):
        _backend_runtime.state.renderer_camera_frame = np.full((2, 2, 3), 1, dtype=np.uint8)
        _backend_runtime.state.renderer_camera_last_seen_at = 100.0

        for wall_clock in (-1_000_000_000.0, 1_000_000_000.0):
            with self.subTest(wall_clock=wall_clock), patch.object(
                _backend_camera.time,
                "time",
                return_value=wall_clock,
            ), patch.object(_backend_camera.time, "monotonic", return_value=104.0):
                self.assertTrue(_backend_camera.is_renderer_camera_active())

    def test_renderer_liveness_expires_from_monotonic_age(self):
        _backend_runtime.state.renderer_camera_frame = np.full((2, 2, 3), 1, dtype=np.uint8)
        _backend_runtime.state.renderer_camera_last_seen_at = 100.0

        self.assertFalse(_backend_camera.is_renderer_camera_active(105.001))

    def test_renderer_liveness_rejects_future_monotonic_timestamp(self):
        _backend_runtime.state.renderer_camera_frame = np.full((2, 2, 3), 1, dtype=np.uint8)
        _backend_runtime.state.renderer_camera_last_seen_at = 100.001

        self.assertFalse(_backend_camera.is_renderer_camera_active(100.0))

    def test_renderer_upload_atomically_takes_ownership_from_open_physical_capture(self):
        renderer_input = np.full((6, 8, 3), 127, dtype=np.uint8)
        ok, encoded = _backend_camera.cv2.imencode(".jpg", renderer_input)
        self.assertTrue(ok)
        payloads = []

        def upload_renderer_during_physical_read():
            payloads.append(
                asyncio.run(
                    _backend_camera.receive_renderer_camera_frame(
                        _FakeRequest(
                            encoded.tobytes(),
                            {
                                "content-type": "image/jpeg",
                                "x-vantage-intent": _backend_camera.RENDERER_CAMERA_FRAME_INTENT,
                            },
                        )
                    )
                )
            )
            _backend_runtime.state.is_running = False
            return True, np.full((6, 8, 3), 240, dtype=np.uint8)

        physical_camera = _OpenPhysicalCapture(
            on_read=upload_renderer_during_physical_read
        )
        _backend_runtime.state.camera = physical_camera
        _backend_runtime.state.is_running = True

        with patch.object(_backend_camera.time, "sleep", return_value=None):
            _backend_camera.camera_loop()

        published_renderer_frame = _backend_runtime.state.renderer_camera_frame.copy()

        self.assertTrue(payloads[0]["ok"])
        self.assertIs(_backend_runtime.state.camera, _backend_runtime.state.renderer_camera)
        self.assertTrue(
            np.array_equal(_backend_runtime.state.latest_frame, published_renderer_frame)
        )
        self.assertIsNotNone(_backend_runtime.state.renderer_camera_last_seen_at)
        self.assertEqual(
            _backend_runtime.state.latest_frame_published_at,
            _backend_runtime.state.renderer_camera_last_seen_at,
        )
        self.assertEqual(physical_camera.release_count, 1)

    def test_shutdown_drains_physical_capture_displaced_by_renderer_upload(self):
        physical_camera = _OpenPhysicalCapture()
        _backend_runtime.state.camera = physical_camera
        renderer_input = np.full((6, 8, 3), 127, dtype=np.uint8)
        ok, encoded = _backend_camera.cv2.imencode(".jpg", renderer_input)
        self.assertTrue(ok)

        asyncio.run(
            _backend_camera.receive_renderer_camera_frame(
                _FakeRequest(
                    encoded.tobytes(),
                    {
                        "content-type": "image/jpeg",
                        "x-vantage-intent": _backend_camera.RENDERER_CAMERA_FRAME_INTENT,
                    },
                )
            )
        )
        asyncio.run(_backend_runtime.shutdown_event())

        self.assertEqual(physical_camera.release_count, 1)
        self.assertEqual(_backend_runtime.state.camera_release_queue, [])
        self.assertEqual(_backend_runtime.state.camera_release_ids, set())
        self.assertIsNone(_backend_runtime.state.latest_frame)
        self.assertIsNone(_backend_runtime.state.latest_frame_published_at)

    def test_shutdown_waits_for_inflight_read_and_releases_capture_once(self):
        read_started = threading.Event()
        allow_read_to_finish = threading.Event()
        shutdown_finished = threading.Event()

        def blocking_read():
            read_started.set()
            allow_read_to_finish.wait(timeout=5)
            return False, None

        physical_camera = _OpenPhysicalCapture(on_read=blocking_read)
        _backend_runtime.state.camera = physical_camera
        _backend_runtime.state.is_running = True
        camera_thread = threading.Thread(target=_backend_camera.camera_loop)

        def run_shutdown():
            asyncio.run(_backend_runtime.shutdown_event())
            shutdown_finished.set()

        shutdown_thread = threading.Thread(target=run_shutdown)
        with patch.object(_backend_camera.time, "sleep", return_value=None):
            camera_thread.start()
            self.assertTrue(read_started.wait(timeout=2))
            shutdown_thread.start()

            deadline = time.monotonic() + 2
            while _backend_runtime.state.is_running and time.monotonic() < deadline:
                time.sleep(0.01)
            shutdown_completed_while_read_blocked = shutdown_finished.wait(timeout=0.1)

            allow_read_to_finish.set()
            camera_thread.join(timeout=2)
            shutdown_thread.join(timeout=2)

        self.assertFalse(shutdown_completed_while_read_blocked)
        self.assertFalse(camera_thread.is_alive())
        self.assertFalse(shutdown_thread.is_alive())
        self.assertEqual(physical_camera.release_count, 1)
        self.assertEqual(_backend_runtime.state.camera_release_queue, [])
        self.assertEqual(_backend_runtime.state.camera_release_ids, set())

    def test_renderer_camera_frame_requires_local_intent_header(self):
        response = asyncio.run(
            _backend_camera.receive_renderer_camera_frame(
                _FakeRequest(
                    b"not a frame",
                    {
                        "content-type": "image/jpeg",
                    },
                )
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_status_reports_dark_camera_frame(self):
        _backend_runtime.state.latest_frame = np.zeros((6, 8, 3), dtype=np.uint8)

        payload = _backend_system._build_status_payload()

        self.assertTrue(payload["camera_frame_available"])
        self.assertTrue(payload["camera_frame_dark"])
        self.assertEqual(payload["camera_frame_mean_luma"], 0.0)


if __name__ == "__main__":
    unittest.main()

import asyncio
import unittest
from unittest.mock import patch

import numpy as np

from src import server


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
        self.original_camera = server.state.camera
        self.original_renderer_camera = getattr(server.state, "renderer_camera", None)
        self.original_renderer_frame = getattr(server.state, "renderer_camera_frame", None)
        self.original_renderer_last_seen_at = getattr(server.state, "renderer_camera_last_seen_at", None)
        self.original_latest_frame = getattr(server.state, "latest_frame", None)
        self.original_is_running = server.state.is_running
        self.original_release_queue = list(server.state.camera_release_queue)
        self.original_release_ids = set(server.state.camera_release_ids)

    def tearDown(self):
        server.state.camera = self.original_camera
        server.state.renderer_camera = self.original_renderer_camera
        server.state.renderer_camera_frame = self.original_renderer_frame
        server.state.renderer_camera_last_seen_at = self.original_renderer_last_seen_at
        server.state.latest_frame = self.original_latest_frame
        server.state.is_running = self.original_is_running
        server.state.camera_release_queue = self.original_release_queue
        server.state.camera_release_ids = self.original_release_ids

    def test_renderer_camera_frame_updates_backend_camera_state(self):
        frame = np.full((6, 8, 3), 127, dtype=np.uint8)
        ok, encoded = server.cv2.imencode(".jpg", frame)
        self.assertTrue(ok)

        payload = asyncio.run(
            server.receive_renderer_camera_frame(
                _FakeRequest(
                    encoded.tobytes(),
                    {
                        "content-type": "image/jpeg",
                        "x-vantage-intent": server.RENDERER_CAMERA_FRAME_INTENT,
                    },
                )
            )
        )

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["camera_online"])
        self.assertEqual(payload["width"], 8)
        self.assertEqual(payload["height"], 6)
        self.assertTrue(server._camera_online())
        self.assertIs(server.state.camera, server.state.renderer_camera)

        success, captured = server.state.camera.read()
        self.assertTrue(success)
        self.assertEqual(captured.shape, (6, 8, 3))
        self.assertEqual(server.state.latest_frame.shape, (6, 8, 3))

    def test_renderer_upload_atomically_takes_ownership_from_open_physical_capture(self):
        renderer_input = np.full((6, 8, 3), 127, dtype=np.uint8)
        ok, encoded = server.cv2.imencode(".jpg", renderer_input)
        self.assertTrue(ok)
        payloads = []

        def upload_renderer_during_physical_read():
            payloads.append(
                asyncio.run(
                    server.receive_renderer_camera_frame(
                        _FakeRequest(
                            encoded.tobytes(),
                            {
                                "content-type": "image/jpeg",
                                "x-vantage-intent": server.RENDERER_CAMERA_FRAME_INTENT,
                            },
                        )
                    )
                )
            )
            server.state.is_running = False
            return True, np.full((6, 8, 3), 240, dtype=np.uint8)

        physical_camera = _OpenPhysicalCapture(
            on_read=upload_renderer_during_physical_read
        )
        server.state.camera = physical_camera
        server.state.is_running = True

        with patch.object(server.time, "sleep", return_value=None):
            server.camera_loop()

        published_renderer_frame = server.state.renderer_camera_frame.copy()

        self.assertTrue(payloads[0]["ok"])
        self.assertIs(server.state.camera, server.state.renderer_camera)
        self.assertTrue(
            np.array_equal(server.state.latest_frame, published_renderer_frame)
        )
        self.assertEqual(physical_camera.release_count, 1)

    def test_shutdown_drains_physical_capture_displaced_by_renderer_upload(self):
        physical_camera = _OpenPhysicalCapture()
        server.state.camera = physical_camera
        renderer_input = np.full((6, 8, 3), 127, dtype=np.uint8)
        ok, encoded = server.cv2.imencode(".jpg", renderer_input)
        self.assertTrue(ok)

        asyncio.run(
            server.receive_renderer_camera_frame(
                _FakeRequest(
                    encoded.tobytes(),
                    {
                        "content-type": "image/jpeg",
                        "x-vantage-intent": server.RENDERER_CAMERA_FRAME_INTENT,
                    },
                )
            )
        )
        asyncio.run(server.shutdown_event())

        self.assertEqual(physical_camera.release_count, 1)
        self.assertEqual(server.state.camera_release_queue, [])
        self.assertEqual(server.state.camera_release_ids, set())

    def test_renderer_camera_frame_requires_local_intent_header(self):
        response = asyncio.run(
            server.receive_renderer_camera_frame(
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
        server.state.latest_frame = np.zeros((6, 8, 3), dtype=np.uint8)

        payload = server._build_status_payload()

        self.assertTrue(payload["camera_frame_available"])
        self.assertTrue(payload["camera_frame_dark"])
        self.assertEqual(payload["camera_frame_mean_luma"], 0.0)


if __name__ == "__main__":
    unittest.main()

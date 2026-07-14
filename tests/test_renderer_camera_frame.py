import asyncio
import unittest

import numpy as np

from src import server


class _FakeRequest:
    def __init__(self, body, headers):
        self._body = body
        self.headers = headers

    async def body(self):
        return self._body


class _OpenPhysicalCapture:
    def __init__(self):
        self.release_count = 0

    def isOpened(self):
        return True

    def release(self):
        self.release_count += 1


class RendererCameraFrameTests(unittest.TestCase):
    def setUp(self):
        self.original_camera = server.state.camera
        self.original_renderer_camera = getattr(server.state, "renderer_camera", None)
        self.original_renderer_frame = getattr(server.state, "renderer_camera_frame", None)
        self.original_renderer_last_seen_at = getattr(server.state, "renderer_camera_last_seen_at", None)
        self.original_latest_frame = getattr(server.state, "latest_frame", None)

    def tearDown(self):
        server.state.camera = self.original_camera
        server.state.renderer_camera = self.original_renderer_camera
        server.state.renderer_camera_frame = self.original_renderer_frame
        server.state.renderer_camera_last_seen_at = self.original_renderer_last_seen_at
        server.state.latest_frame = self.original_latest_frame

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
        physical_camera = _OpenPhysicalCapture()
        server.state.camera = physical_camera
        renderer_input = np.full((6, 8, 3), 127, dtype=np.uint8)
        ok, encoded = server.cv2.imencode(".jpg", renderer_input)
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
        published_renderer_frame = server.state.renderer_camera_frame.copy()

        stale_physical_frame = np.full((6, 8, 3), 240, dtype=np.uint8)
        self.assertFalse(
            server._publish_camera_frame(physical_camera, stale_physical_frame)
        )
        server._retire_camera_capture(physical_camera)

        self.assertTrue(payload["ok"])
        self.assertIs(server.state.camera, server.state.renderer_camera)
        self.assertTrue(
            np.array_equal(server.state.latest_frame, published_renderer_frame)
        )
        self.assertEqual(physical_camera.release_count, 1)

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

import asyncio
import unittest
from unittest.mock import patch

from src import server


class _DummyCamera:
    def __init__(self, opened):
        self._opened = opened

    def isOpened(self):
        return self._opened


class FaceLiveEndpointTests(unittest.TestCase):
    def setUp(self):
        self.original_points = getattr(server.state, "live_face_points", None)
        self.original_camera = server.state.camera

    def tearDown(self):
        server.state.live_face_points = [] if self.original_points is None else self.original_points
        server.state.camera = self.original_camera

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

    def test_live_sampling_interval_is_100ms(self):
        self.assertEqual(server.FACE_LIVE_SAMPLE_INTERVAL_SECONDS, 0.1)


if __name__ == "__main__":
    unittest.main()

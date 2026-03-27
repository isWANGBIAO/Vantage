import asyncio

from src import server


class _DummyCamera:
    def __init__(self):
        self.released = False

    def release(self):
        self.released = True


def test_shutdown_event_stops_loops_and_releases_camera():
    original_camera = server.state.camera
    original_running = server.state.is_running
    dummy_camera = _DummyCamera()

    try:
        server.state.camera = dummy_camera
        server.state.is_running = True

        asyncio.run(server.shutdown_event())

        assert server.state.is_running is False
        assert dummy_camera.released is True
        assert server.state.camera is None
    finally:
        server.state.camera = original_camera
        server.state.is_running = original_running

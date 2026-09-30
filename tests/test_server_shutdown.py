import asyncio

from src.backend import runtime as _backend_runtime


class _DummyCamera:
    def __init__(self):
        self.released = False

    def release(self):
        self.released = True


def test_shutdown_event_stops_loops_and_releases_camera():
    original_camera = _backend_runtime.state.camera
    original_running = _backend_runtime.state.is_running
    dummy_camera = _DummyCamera()

    try:
        _backend_runtime.state.camera = dummy_camera
        _backend_runtime.state.is_running = True

        asyncio.run(_backend_runtime.shutdown_event())

        assert _backend_runtime.state.is_running is False
        assert dummy_camera.released is True
        assert _backend_runtime.state.camera is None
    finally:
        _backend_runtime.state.camera = original_camera
        _backend_runtime.state.is_running = original_running

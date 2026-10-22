"""Real loop boundaries driven by synthetic frames; no hardware or model startup."""

import asyncio
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import httpx
import numpy as np
import pytest
from fastapi import FastAPI

from src.backend import camera, face, media, runtime
from src.manager.take_photo.take_a_photo import PresencePhotoMinuteGate, PresencePhotoSaveCoordinator
from src.utils.photo_identity import photo_filename


@pytest.fixture
def observation(monkeypatch, tmp_path):
    state = runtime.SystemState()
    monkeypatch.setattr(runtime, "state", state)
    state.camera = SimpleNamespace(isOpened=lambda: True, release=lambda: None)
    state.latest_frame = np.full((8, 8, 3), 30, np.uint8)
    state.latest_frame_published_at = 100.0
    state.latest_frame_observed_at = datetime.now()
    state.photos_path = str(tmp_path / "photos")
    clock = [100.0]
    monkeypatch.setattr(camera.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(camera.time, "sleep", lambda _: setattr(state, "is_running", False))
    monkeypatch.setattr(runtime, "wait_for_next_inference_start", lambda *_: clock[0])
    monkeypatch.setattr(camera, "get_face_detector", lambda: object())
    monkeypatch.setattr(camera, "should_run_face_live_analysis", lambda: True)
    monkeypatch.setattr(face, "get_face_analysis_runtime", lambda: (None, None, None))
    monkeypatch.setattr(cv2, "VideoCapture", lambda *_: pytest.fail("Real camera forbidden"))
    return state, clock


def test_live_loop_skips_retained_stale_frame_and_public_endpoint_cannot_call_it_current(observation, monkeypatch):
    state, clock = observation
    state.latest_frame_published_at = 40.0
    called = []

    def analyze(*_, **kwargs):
        called.append(kwargs)
        state.is_running = False
        return {"passed": True, "score": 30, "timestamp": state.latest_frame_observed_at.timestamp(), "datetime": state.latest_frame_observed_at.isoformat()}

    monkeypatch.setattr(face, "get_face_analysis_pipeline_module", lambda: SimpleNamespace(analyze_image_data=analyze))
    camera.face_live_loop()
    assert called == []
    assert state.latest_live_face_score is None
    result = asyncio.run(face.get_face_live())
    assert result["latest_score"] is None
    assert result["points"] == []


def test_same_fresh_frame_is_only_one_live_sample_and_keeps_capture_time(observation, monkeypatch):
    state, clock = observation
    captured = state.latest_frame_observed_at
    calls = []
    waits = [0]

    def wait(*_):
        waits[0] += 1
        clock[0] = 100.0 + waits[0]
        if waits[0] == 4:
            state.is_running = False
        return clock[0]

    def analyze(*_, **kwargs):
        calls.append(kwargs)
        return {"passed": True, "score": 30, "timestamp": captured.timestamp(), "datetime": captured.strftime("%Y-%m-%d %H:%M:%S")}

    monkeypatch.setattr(runtime, "wait_for_next_inference_start", wait)
    monkeypatch.setattr(camera.time, "sleep", lambda _: None)
    monkeypatch.setattr(face, "get_face_analysis_pipeline_module", lambda: SimpleNamespace(analyze_image_data=analyze))
    camera.face_live_loop()
    assert len(calls) == 1
    assert calls[0]["observed_at"] == captured
    assert len(state.live_face_points) == 1


@pytest.mark.parametrize("change", ["stale", "retired", "fresh-same-source"])
def test_live_result_is_not_published_after_its_observation_becomes_invalid(observation, monkeypatch, change):
    state, clock = observation
    captured = state.latest_frame_observed_at

    def analyze(*_, **kwargs):
        assert kwargs["observed_at"] == captured
        if change == "stale":
            clock[0] = 160.0
        elif change == "retired":
            state.camera = None
            state.latest_frame = None
        else:
            clock[0] = 101.0
            state.latest_frame_published_at = 101.0
        state.is_running = False
        return {"passed": True, "score": 30, "timestamp": captured.timestamp(), "datetime": captured.strftime("%Y-%m-%d %H:%M:%S")}

    monkeypatch.setattr(face, "get_face_analysis_pipeline_module", lambda: SimpleNamespace(analyze_image_data=analyze))
    camera.face_live_loop()
    assert len(state.live_face_points) == (1 if change == "fresh-same-source" else 0)
    assert state.latest_live_face_score == (30 if change == "fresh-same-source" else None)


@pytest.mark.parametrize("change", ["stale", "renderer", "retired", "fresh-same-source"])
def test_presence_completion_revalidates_frame_and_camera_owner(observation, monkeypatch, change):
    state, clock = observation
    captured = state.latest_frame_observed_at
    submitted = Mock(return_value=True)
    monkeypatch.setattr(media._presence_photo_save_coordinator, "submit", submitted)

    def detect(*_, **kwargs):
        if change == "stale":
            clock[0] = 160.0
        elif change == "renderer":
            app = FastAPI()
            app.include_router(camera.router)
            _, encoded = cv2.imencode('.jpg', np.full((8, 8, 3), 180, np.uint8))

            async def upload():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as http:
                    response = await http.post("/api/v1/camera/frame", content=encoded.tobytes(), headers={
                        "content-type": "image/jpeg", "x-vantage-intent": "renderer-camera-frame",
                    })
                    assert response.status_code == 200

            asyncio.run(upload())
        elif change == "retired":
            state.camera = None
            state.latest_frame = None
        else:
            clock[0] = 101.0
            state.latest_frame = state.latest_frame.copy()
            state.latest_frame_published_at = 101.0
        state.is_running = False
        return [(1, 1, 4, 4)]

    monkeypatch.setattr(camera, "detect_foreground_presence_face_boxes", detect)
    camera.face_detection_loop()
    if change == "fresh-same-source":
        assert submitted.call_count == 1
        assert submitted.call_args.kwargs["captured_at"] == captured
        assert state.person_boxes == [(1, 1, 4, 4)]
    else:
        submitted.assert_not_called()
        assert state.person_boxes == []


def test_valid_presence_save_uses_real_async_worker_without_holding_observation_lock(observation, monkeypatch):
    state, _ = observation
    captured = datetime(2025, 2, 3, 4, 5, 6)
    state.latest_frame_observed_at = captured
    coordinator = PresencePhotoSaveCoordinator(gate=PresencePhotoMinuteGate())
    saved = threading.Event()
    publish = media._publish_presence_photo_path

    def on_success(path):
        publish(path)
        saved.set()

    def detect(*_, **kwargs):
        state.is_running = False
        return [(1, 1, 4, 4)]

    monkeypatch.setattr(media, "_presence_photo_save_coordinator", coordinator)
    monkeypatch.setattr(media, "_publish_presence_photo_path", on_success)
    monkeypatch.setattr(camera, "get_location", lambda: (None, None))
    monkeypatch.setattr(camera, "detect_foreground_presence_face_boxes", detect)
    try:
        camera.face_detection_loop()
        assert saved.wait(3), "The actual async save callback must acquire and release the observation lock"
        path = Path(state.paths["photo"])
        assert path.name == photo_filename(captured)
        assert path.is_file()
        assert float(cv2.imread(str(path)).mean()) == 30.0
    finally:
        coordinator.close(timeout=3)

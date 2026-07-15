from unittest.mock import MagicMock, patch

import numpy as np

from src import server


def test_detection_model_prewarm_flag_zero_keeps_yunet_lazy():
    with (
        patch.object(server, "PREWARM_FACE_ON_STARTUP", False),
        patch.object(server, "PREWARM_FACE_DETECTION_ON_STARTUP", False),
        patch.object(server, "get_face_detector") as get_face_detector,
    ):
        server.prewarm_runtime_models()

    get_face_detector.assert_not_called()


def test_detection_model_prewarm_runs_foreground_presence_inference(capsys):
    face_detector = MagicMock()

    with (
        patch.object(server, "PREWARM_FACE_ON_STARTUP", False),
        patch.object(server, "PREWARM_FACE_DETECTION_ON_STARTUP", True),
        patch.object(server, "get_face_detector", return_value=face_detector) as get_face,
        patch.object(
            server,
            "detect_foreground_presence_face_boxes",
            return_value=[],
        ) as detect_foreground,
    ):
        server.prewarm_runtime_models()

    get_face.assert_called_once_with()
    detect_foreground.assert_called_once()
    frame = detect_foreground.call_args.args[0]
    assert frame.shape == (640, 640, 3)
    assert frame.dtype == np.uint8
    assert np.count_nonzero(frame) == 0
    assert detect_foreground.call_args.kwargs == {
        "model": face_detector,
        "conf": 0.50,
    }
    output = capsys.readouterr().out
    assert "Camera face detector warmed up successfully." in output
    assert "body detector" not in output.lower()


def test_detection_model_prewarm_reports_yunet_load_failure(capsys):
    with (
        patch.object(server, "PREWARM_FACE_ON_STARTUP", False),
        patch.object(server, "PREWARM_FACE_DETECTION_ON_STARTUP", True),
        patch.object(
            server,
            "get_face_detector",
            side_effect=RuntimeError("invalid YuNet model"),
        ),
    ):
        server.prewarm_runtime_models()

    output = capsys.readouterr().out
    assert "Failed to warm camera face detector: invalid YuNet model" in output
    assert "body detector" not in output.lower()


def test_detection_model_prewarm_reports_yunet_inference_failure(capsys):
    face_detector = MagicMock()

    with (
        patch.object(server, "PREWARM_FACE_ON_STARTUP", False),
        patch.object(server, "PREWARM_FACE_DETECTION_ON_STARTUP", True),
        patch.object(server, "get_face_detector", return_value=face_detector),
        patch.object(
            server,
            "detect_foreground_presence_face_boxes",
            side_effect=RuntimeError("YuNet inference failed"),
        ),
    ):
        server.prewarm_runtime_models()

    output = capsys.readouterr().out
    assert "Failed to warm camera face detector: YuNet inference failed" in output
    assert "body detector" not in output.lower()

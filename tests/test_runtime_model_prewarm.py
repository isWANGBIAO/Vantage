from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src import server


def _successful_detection_models():
    face_detector = MagicMock()
    face_detector.detect.return_value = (None, None)
    body_detector = MagicMock()
    body_detector.detect_person_boxes.return_value = []
    return face_detector, body_detector


def test_detection_model_prewarm_flag_zero_keeps_both_detectors_lazy():
    with (
        patch.object(server, "PREWARM_FACE_ON_STARTUP", False),
        patch.object(server, "PREWARM_FACE_DETECTION_ON_STARTUP", False),
        patch.object(server, "get_face_detector") as face_detector,
        patch.object(server, "get_person_presence_detector") as body_detector,
    ):
        server.prewarm_runtime_models()

    face_detector.assert_not_called()
    body_detector.assert_not_called()


@pytest.mark.parametrize("failing_detector", ["face", "body"])
def test_detection_model_prewarm_attempts_both_detectors_when_one_load_fails(
    failing_detector,
    capsys,
):
    face_model, body_model = _successful_detection_models()
    face_error = RuntimeError("invalid YuNet model") if failing_detector == "face" else None
    body_error = RuntimeError("missing YOLOX model") if failing_detector == "body" else None

    with (
        patch.object(server, "PREWARM_FACE_ON_STARTUP", False),
        patch.object(server, "PREWARM_FACE_DETECTION_ON_STARTUP", True),
        patch.object(
            server,
            "get_face_detector",
            side_effect=face_error,
            return_value=face_model,
        ) as face_detector,
        patch.object(
            server,
            "get_person_presence_detector",
            side_effect=body_error,
            return_value=body_model,
        ) as body_detector,
    ):
        server.prewarm_runtime_models()

    face_detector.assert_called_once_with()
    body_detector.assert_called_once_with()
    output = capsys.readouterr().out
    if failing_detector == "face":
        assert "Failed to warm camera face detector: invalid YuNet model" in output
        assert "Camera body detector warmed up successfully." in output
    else:
        assert "Camera face detector warmed up successfully." in output
        assert "Failed to warm camera body detector: missing YOLOX model" in output


def test_detection_model_prewarm_runs_real_inference_entrypoints():
    face_detector, body_detector = _successful_detection_models()

    with (
        patch.object(server, "PREWARM_FACE_ON_STARTUP", False),
        patch.object(server, "PREWARM_FACE_DETECTION_ON_STARTUP", True),
        patch.object(server, "get_face_detector", return_value=face_detector),
        patch.object(
            server,
            "get_person_presence_detector",
            return_value=body_detector,
        ),
    ):
        server.prewarm_runtime_models()

    face_detector.detect.assert_called_once()
    face_frame = face_detector.detect.call_args.args[0]
    body_detector.detect_person_boxes.assert_called_once()
    body_frame = body_detector.detect_person_boxes.call_args.args[0]
    for frame in (face_frame, body_frame):
        assert frame.shape == (640, 640, 3)
        assert frame.dtype == np.uint8
        assert np.count_nonzero(frame) == 0


@pytest.mark.parametrize("failing_detector", ["face", "body"])
def test_detection_model_prewarm_reports_inference_failure_and_continues(
    failing_detector,
    capsys,
):
    face_detector, body_detector = _successful_detection_models()
    if failing_detector == "face":
        face_detector.detect.side_effect = RuntimeError("YuNet inference failed")
    else:
        body_detector.detect_person_boxes.side_effect = RuntimeError(
            "YOLOX inference failed"
        )

    with (
        patch.object(server, "PREWARM_FACE_ON_STARTUP", False),
        patch.object(server, "PREWARM_FACE_DETECTION_ON_STARTUP", True),
        patch.object(server, "get_face_detector", return_value=face_detector) as get_face,
        patch.object(
            server,
            "get_person_presence_detector",
            return_value=body_detector,
        ) as get_body,
    ):
        server.prewarm_runtime_models()

    get_face.assert_called_once_with()
    get_body.assert_called_once_with()
    face_detector.detect.assert_called_once()
    body_detector.detect_person_boxes.assert_called_once()
    output = capsys.readouterr().out
    if failing_detector == "face":
        assert "Failed to warm camera face detector: YuNet inference failed" in output
        assert "Camera body detector warmed up successfully." in output
    else:
        assert "Camera face detector warmed up successfully." in output
        assert "Failed to warm camera body detector: YOLOX inference failed" in output

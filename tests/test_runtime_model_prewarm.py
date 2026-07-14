from unittest.mock import patch

import pytest

from src import server


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
def test_detection_model_prewarm_attempts_both_detectors_when_one_fails(
    failing_detector,
    capsys,
):
    face_error = RuntimeError("invalid YuNet model") if failing_detector == "face" else None
    body_error = RuntimeError("missing YOLOX model") if failing_detector == "body" else None

    with (
        patch.object(server, "PREWARM_FACE_ON_STARTUP", False),
        patch.object(server, "PREWARM_FACE_DETECTION_ON_STARTUP", True),
        patch.object(server, "get_face_detector", side_effect=face_error) as face_detector,
        patch.object(
            server,
            "get_person_presence_detector",
            side_effect=body_error,
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

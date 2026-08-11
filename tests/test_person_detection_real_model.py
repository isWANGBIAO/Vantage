from pathlib import Path

import cv2

from src.services import person_detection


FIXTURE_PATH = Path("tests/fixtures/yunet/foreground_face_cc0.jpg")
REPOSITORY_MODEL_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "models"
    / "face_detection_yunet_2023mar.onnx"
)


def test_real_yunet_detects_one_qualifying_foreground_face(monkeypatch):
    image = cv2.imread(str(FIXTURE_PATH))
    assert image is not None, "CC0 YuNet fixture must be readable"

    monkeypatch.delenv(
        person_detection.FACE_DETECTION_MODEL_PATH_ENV,
        raising=False,
    )
    model_path = REPOSITORY_MODEL_PATH
    assert person_detection.resolve_face_detection_model_path() == model_path
    assert model_path.is_file(), "the checked-in YuNet model must be available"

    detector = cv2.FaceDetectorYN_create(
        str(model_path),
        "",
        person_detection.FACE_DETECTION_INPUT_SIZE,
        person_detection.PERSON_DETECTION_CONFIDENCE,
        person_detection.FACE_DETECTION_NMS_THRESHOLD,
        person_detection.FACE_DETECTION_TOP_K,
    )
    boxes = person_detection.detect_foreground_presence_face_boxes(
        image,
        model=detector,
    )

    assert len(boxes) == 1
    image_height, image_width = image.shape[:2]
    x1, y1, x2, y2 = boxes[0]
    assert 0 <= x1 < x2 < image_width
    assert 0 <= y1 < y2 < image_height

    face_area_ratio = ((x2 - x1) * (y2 - y1)) / float(
        image_width * image_height
    )
    assert face_area_ratio >= person_detection.PRESENCE_MIN_FACE_AREA_RATIO

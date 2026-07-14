"""Camera-facing face detection used by the legacy person-presence APIs.

YuNet's five landmarks support a coarse frontal-pose geometry check. They do
not reveal where a person is looking, so this module is not eye or gaze
tracking.
"""

from __future__ import annotations

import math
import os
import sys
import threading
from pathlib import Path
from typing import Any, Iterable


PERSON_DETECTION_CONFIDENCE = 0.75
PERSON_DETECTION_MODEL = "face_detection_yunet_2023mar.onnx"
FACE_DETECTION_MODEL_PATH_ENV = "VANTAGE_FACE_DETECTION_MODEL_PATH"
FACE_DETECTION_INPUT_SIZE = (320, 320)
FACE_DETECTION_NMS_THRESHOLD = 0.3
FACE_DETECTION_TOP_K = 5000

_FACE_DETECTOR = None
_FACE_DETECTOR_LOCK = threading.RLock()


def _model_path_candidates() -> list[Path]:
    source_src_dir = Path(__file__).resolve().parents[1]
    candidates = []

    meipass_root = getattr(sys, "_MEIPASS", None)
    if meipass_root:
        candidates.extend(
            [
                Path(meipass_root) / PERSON_DETECTION_MODEL,
                Path(meipass_root) / "src" / "models" / PERSON_DETECTION_MODEL,
                Path(meipass_root) / "models" / PERSON_DETECTION_MODEL,
            ]
        )

    candidates.append(source_src_dir / "models" / PERSON_DETECTION_MODEL)

    executable_parent = Path(sys.executable).resolve().parent
    candidates.extend(
        [
            executable_parent / "_internal" / PERSON_DETECTION_MODEL,
            executable_parent / "_internal" / "src" / "models" / PERSON_DETECTION_MODEL,
            executable_parent / "_internal" / "models" / PERSON_DETECTION_MODEL,
            executable_parent / PERSON_DETECTION_MODEL,
            executable_parent / "src" / "models" / PERSON_DETECTION_MODEL,
            executable_parent / "models" / PERSON_DETECTION_MODEL,
            Path.cwd() / "src" / "models" / PERSON_DETECTION_MODEL,
        ]
    )

    unique_candidates = []
    seen = set()
    for candidate in candidates:
        normalized = os.path.normcase(str(candidate.resolve()))
        if normalized not in seen:
            seen.add(normalized)
            unique_candidates.append(candidate)
    return unique_candidates


def resolve_face_detection_model_path() -> Path:
    configured_path = os.environ.get(FACE_DETECTION_MODEL_PATH_ENV)
    if configured_path:
        model_path = Path(configured_path).expanduser()
        if model_path.is_file():
            return model_path.resolve()
        raise FileNotFoundError(
            f"Configured face detection model does not exist: {model_path} "
            f"({FACE_DETECTION_MODEL_PATH_ENV})"
        )

    candidates = _model_path_candidates()
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    searched_paths = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(
        f"Missing face detection model {PERSON_DETECTION_MODEL}; searched: {searched_paths}"
    )


def get_face_detector():
    global _FACE_DETECTOR
    if _FACE_DETECTOR is not None:
        return _FACE_DETECTOR

    with _FACE_DETECTOR_LOCK:
        if _FACE_DETECTOR is None:
            import cv2

            model_path = resolve_face_detection_model_path()
            _FACE_DETECTOR = cv2.FaceDetectorYN_create(
                str(model_path),
                "",
                FACE_DETECTION_INPUT_SIZE,
                PERSON_DETECTION_CONFIDENCE,
                FACE_DETECTION_NMS_THRESHOLD,
                FACE_DETECTION_TOP_K,
            )
    return _FACE_DETECTOR


def _point_is_inside_face(point: tuple[float, float], bounds: tuple[float, float, float, float]) -> bool:
    px, py = point
    x1, y1, x2, y2 = bounds
    return x1 <= px <= x2 and y1 <= py <= y2


def _balanced_about(center_x: float, left_x: float, right_x: float, minimum_ratio: float) -> bool:
    left_distance = center_x - left_x
    right_distance = right_x - center_x
    if left_distance <= 0 or right_distance <= 0:
        return False
    return min(left_distance, right_distance) / max(left_distance, right_distance) >= minimum_ratio


def is_roughly_frontal_face(face: Iterable[float]) -> bool:
    """Return whether YuNet landmarks describe a roughly frontal head pose.

    This checks landmark geometry only. It is deliberately not an eye-tracking
    or gaze-estimation signal.
    """

    try:
        values = [float(value) for value in face]
    except (TypeError, ValueError):
        return False

    if len(values) < 15 or not all(math.isfinite(value) for value in values[:15]):
        return False

    x, y, width, height = values[:4]
    if width <= 0 or height <= 0:
        return False

    eyes = sorted(((values[4], values[5]), (values[6], values[7])))
    nose = (values[8], values[9])
    mouth = sorted(((values[10], values[11]), (values[12], values[13])))
    bounds = (x, y, x + width, y + height)

    if not all(_point_is_inside_face(point, bounds) for point in (*eyes, nose, *mouth)):
        return False

    left_eye, right_eye = eyes
    left_mouth, right_mouth = mouth
    eye_span = right_eye[0] - left_eye[0]
    mouth_span = right_mouth[0] - left_mouth[0]
    if not 0.22 * width <= eye_span <= 0.65 * width:
        return False
    if not 0.12 * width <= mouth_span <= 0.55 * width:
        return False
    if abs(left_eye[1] - right_eye[1]) > 0.12 * height:
        return False
    if abs(left_mouth[1] - right_mouth[1]) > 0.12 * height:
        return False

    eye_mid_x = (left_eye[0] + right_eye[0]) / 2.0
    eye_mid_y = (left_eye[1] + right_eye[1]) / 2.0
    mouth_mid_x = (left_mouth[0] + right_mouth[0]) / 2.0
    mouth_mid_y = (left_mouth[1] + right_mouth[1]) / 2.0

    if not y + 0.12 * height <= eye_mid_y <= y + 0.52 * height:
        return False
    if not eye_mid_y + 0.10 * height <= nose[1] <= mouth_mid_y - 0.08 * height:
        return False
    if not y + 0.52 * height <= mouth_mid_y <= y + 0.92 * height:
        return False

    if abs(eye_mid_x - mouth_mid_x) > 0.12 * width:
        return False
    if abs(nose[0] - eye_mid_x) > 0.14 * width:
        return False
    if abs(nose[0] - mouth_mid_x) > 0.16 * width:
        return False
    if not _balanced_about(nose[0], left_eye[0], right_eye[0], 0.45):
        return False
    return True


def _valid_image_size(source: Any) -> tuple[int, int] | None:
    if source is None or getattr(source, "size", 0) == 0:
        return None
    shape = getattr(source, "shape", ())
    if len(shape) < 2:
        return None
    height, width = int(shape[0]), int(shape[1])
    if height <= 0 or width <= 0:
        return None
    return width, height


def detect_camera_facing_faces(
    source: Any,
    model=None,
    conf: float = PERSON_DETECTION_CONFIDENCE,
) -> list[Any]:
    image_size = _valid_image_size(source)
    if image_size is None:
        return []

    detector = model or get_face_detector()
    with _FACE_DETECTOR_LOCK:
        detector.setInputSize(image_size)
        if hasattr(detector, "setScoreThreshold"):
            detector.setScoreThreshold(float(conf))
        _, faces = detector.detect(source)

    if faces is None:
        return []
    return [face for face in faces if is_roughly_frontal_face(face)]


def detect_face_boxes(
    source: Any,
    model=None,
    conf: float = PERSON_DETECTION_CONFIDENCE,
) -> list[tuple[int, int, int, int]]:
    image_size = _valid_image_size(source)
    if image_size is None:
        return []

    image_width, image_height = image_size
    boxes = []
    for face in detect_camera_facing_faces(source, model=model, conf=conf):
        x, y, width, height = (float(value) for value in face[:4])
        x1 = max(0, min(image_width - 1, int(round(x))))
        y1 = max(0, min(image_height - 1, int(round(y))))
        x2 = max(x1, min(image_width - 1, int(round(x + width))))
        y2 = max(y1, min(image_height - 1, int(round(y + height))))
        boxes.append((x1, y1, x2, y2))
    return boxes


def detect_person_counts(
    sources: list[Any],
    model=None,
    conf: float = PERSON_DETECTION_CONFIDENCE,
) -> list[int]:
    valid_sizes = [_valid_image_size(source) for source in sources]
    if model is None and not any(size is not None for size in valid_sizes):
        return [0 for _ in sources]

    detector = model or get_face_detector()
    return [
        len(detect_camera_facing_faces(source, model=detector, conf=conf))
        if image_size is not None
        else 0
        for source, image_size in zip(sources, valid_sizes)
    ]


def detect_person_count(
    source: Any,
    model=None,
    conf: float = PERSON_DETECTION_CONFIDENCE,
) -> int:
    if _valid_image_size(source) is None:
        return 0
    return detect_person_counts([source], model=model, conf=conf)[0]

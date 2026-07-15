"""YuNet face signals for presence and camera-facing classification.

Presence uses the largest sufficiently foreground YuNet face without imposing
a head-pose constraint. YuNet's five landmarks separately support the stricter
historical camera-facing classification. They do not reveal where a person is
looking, so this module is not eye or gaze tracking.
"""

from __future__ import annotations

import math
import os
import sys
import threading
from pathlib import Path
from typing import Any, Iterable


PERSON_DETECTION_CONFIDENCE = 0.75
PRESENCE_DETECTION_CONFIDENCE = 0.50
PRESENCE_MIN_FACE_AREA_RATIO = 0.005
PERSON_DETECTION_MODEL = "face_detection_yunet_2023mar.onnx"
FACE_DETECTION_MODEL_PATH_ENV = "VANTAGE_FACE_DETECTION_MODEL_PATH"
FACE_DETECTION_INPUT_SIZE = (320, 320)
FACE_DETECTION_NMS_THRESHOLD = 0.3
FACE_DETECTION_TOP_K = 5000
_FACE_DETECTOR = None
_FACE_DETECTOR_LOCK = threading.RLock()


class PresenceDetectionUnavailable(RuntimeError):
    """Raised when absence cannot be trusted because a detector failed."""


def _model_path_candidates(model_name: str) -> list[Path]:
    source_src_dir = Path(__file__).resolve().parents[1]
    candidates = []

    meipass_root = getattr(sys, "_MEIPASS", None)
    if meipass_root:
        candidates.extend(
            [
                Path(meipass_root) / model_name,
                Path(meipass_root) / "src" / "models" / model_name,
                Path(meipass_root) / "models" / model_name,
            ]
        )

    candidates.append(source_src_dir / "models" / model_name)

    executable_parent = Path(sys.executable).resolve().parent
    candidates.extend(
        [
            executable_parent / "_internal" / model_name,
            executable_parent / "_internal" / "src" / "models" / model_name,
            executable_parent / "_internal" / "models" / model_name,
            executable_parent / model_name,
            executable_parent / "src" / "models" / model_name,
            executable_parent / "models" / model_name,
            Path.cwd() / "src" / "models" / model_name,
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


def _resolve_detection_model_path(model_name: str, environment_variable: str) -> Path:
    configured_path = os.environ.get(environment_variable)
    if configured_path:
        model_path = Path(configured_path).expanduser()
        if model_path.is_file():
            return model_path.resolve()
        raise FileNotFoundError(
            f"Configured detection model does not exist: {model_path} "
            f"({environment_variable})"
        )

    candidates = _model_path_candidates(model_name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    searched_paths = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(
        f"Missing detection model {model_name}; searched: {searched_paths}"
    )


def resolve_face_detection_model_path() -> Path:
    return _resolve_detection_model_path(
        PERSON_DETECTION_MODEL,
        FACE_DETECTION_MODEL_PATH_ENV,
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


def _detect_yunet_faces(
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
    return list(faces)


def _validated_presence_face(
    face: Any,
    image_size: tuple[int, int],
) -> tuple[Any, float, tuple[float, float, float, float]]:
    try:
        raw_values = list(face)
        values = [float(value) for value in raw_values[:15]]
    except (OverflowError, TypeError, ValueError) as exc:
        raise PresenceDetectionUnavailable("Invalid YuNet presence output") from exc

    if len(values) < 15 or not all(math.isfinite(value) for value in values[:15]):
        raise PresenceDetectionUnavailable("Invalid YuNet presence output")

    x, y, width, height = values[:4]
    if width <= 0 or height <= 0:
        raise PresenceDetectionUnavailable("Invalid YuNet presence output")

    image_width, image_height = image_size
    x1 = max(0.0, min(float(image_width), x))
    y1 = max(0.0, min(float(image_height), y))
    x2 = max(0.0, min(float(image_width), x + width))
    y2 = max(0.0, min(float(image_height), y + height))
    if x2 <= x1 or y2 <= y1:
        raise PresenceDetectionUnavailable("Invalid YuNet presence output")

    area = (x2 - x1) * (y2 - y1)
    return face, area, (x1, y1, x2, y2)


def detect_presence_faces(
    source: Any,
    model=None,
    conf: float = PRESENCE_DETECTION_CONFIDENCE,
) -> list[Any]:
    """Return the largest YuNet face occupying at least 0.5% of the frame."""

    image_size = _valid_image_size(source)
    if image_size is None:
        return []

    try:
        faces = _detect_yunet_faces(source, model=model, conf=conf)
        candidates = [_validated_presence_face(face, image_size) for face in faces]
    except PresenceDetectionUnavailable:
        raise
    except Exception as exc:
        raise PresenceDetectionUnavailable("YuNet presence detection unavailable") from exc

    frame_area = float(image_size[0] * image_size[1])
    qualifying = [
        candidate
        for candidate in candidates
        if candidate[1] / frame_area >= PRESENCE_MIN_FACE_AREA_RATIO
    ]
    if not qualifying:
        return []
    return [max(qualifying, key=lambda candidate: candidate[1])[0]]


def detect_camera_facing_faces(
    source: Any,
    model=None,
    conf: float = PERSON_DETECTION_CONFIDENCE,
) -> list[Any]:
    return [
        face
        for face in _detect_yunet_faces(source, model=model, conf=conf)
        if is_roughly_frontal_face(face)
    ]


def detect_presence_count(
    source: Any,
    model=None,
    conf: float = PRESENCE_DETECTION_CONFIDENCE,
) -> int:
    if _valid_image_size(source) is None:
        return 0
    return int(bool(detect_presence_faces(source, model=model, conf=conf)))


def detect_foreground_presence_face_boxes(
    source: Any,
    model=None,
    conf: float = PRESENCE_DETECTION_CONFIDENCE,
) -> list[tuple[int, int, int, int]]:
    """Return the single qualifying foreground presence face as corner bounds."""

    image_size = _valid_image_size(source)
    if image_size is None:
        return []

    image_width, image_height = image_size
    boxes = []
    for face in detect_presence_faces(source, model=model, conf=conf):
        _, _, (x1, y1, x2, y2) = _validated_presence_face(face, image_size)
        boxes.append(
            (
                max(0, min(image_width - 1, int(round(x1)))),
                max(0, min(image_height - 1, int(round(y1)))),
                max(0, min(image_width - 1, int(round(x2)))),
                max(0, min(image_height - 1, int(round(y2)))),
            )
        )
    return boxes


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

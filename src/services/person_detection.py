"""Lightweight face and body signals for presence classification.

Presence accepts either a YuNet face or an OpenCV-DNN YOLOX ``person`` result.
YuNet's five landmarks additionally support a coarse frontal-pose geometry
check for camera-facing classification. They do not reveal where a person is
looking, so this module is not eye or gaze tracking.
"""

from __future__ import annotations

import math
import os
import sys
import threading
from pathlib import Path
from typing import Any, Iterable

import numpy as np


PERSON_DETECTION_CONFIDENCE = 0.75
PRESENCE_DETECTION_CONFIDENCE = 0.50
PERSON_DETECTION_MODEL = "face_detection_yunet_2023mar.onnx"
FACE_DETECTION_MODEL_PATH_ENV = "VANTAGE_FACE_DETECTION_MODEL_PATH"
FACE_DETECTION_INPUT_SIZE = (320, 320)
FACE_DETECTION_NMS_THRESHOLD = 0.3
FACE_DETECTION_TOP_K = 5000
PRESENCE_PERSON_DETECTION_CONFIDENCE = 0.50
PRESENCE_PERSON_DETECTION_MODEL = "object_detection_yolox_2022nov_int8bq.onnx"
PERSON_PRESENCE_MODEL_PATH_ENV = "VANTAGE_PERSON_PRESENCE_MODEL_PATH"
YOLOX_INPUT_SIZE = (640, 640)
YOLOX_NMS_THRESHOLD = 0.50
YOLOX_PERSON_CLASS_ID = 0
YOLOX_CLASS_COUNT = 80
YOLOX_STRIDES = (8, 16, 32)

_FACE_DETECTOR = None
_FACE_DETECTOR_LOCK = threading.RLock()
_PERSON_PRESENCE_DETECTOR = None
_PERSON_PRESENCE_DETECTOR_LOCK = threading.RLock()
_YOLOX_GRID = None
_YOLOX_EXPANDED_STRIDES = None


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


def resolve_person_presence_model_path() -> Path:
    return _resolve_detection_model_path(
        PRESENCE_PERSON_DETECTION_MODEL,
        PERSON_PRESENCE_MODEL_PATH_ENV,
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


def _yolox_grid_and_strides() -> tuple[np.ndarray, np.ndarray]:
    global _YOLOX_GRID, _YOLOX_EXPANDED_STRIDES
    if _YOLOX_GRID is not None and _YOLOX_EXPANDED_STRIDES is not None:
        return _YOLOX_GRID, _YOLOX_EXPANDED_STRIDES

    input_width, input_height = YOLOX_INPUT_SIZE
    grids = []
    expanded_strides = []
    for stride in YOLOX_STRIDES:
        grid_width = input_width // stride
        grid_height = input_height // stride
        grid_x, grid_y = np.meshgrid(
            np.arange(grid_width, dtype=np.float32),
            np.arange(grid_height, dtype=np.float32),
        )
        grid = np.stack((grid_x, grid_y), axis=2).reshape(1, -1, 2)
        grids.append(grid)
        expanded_strides.append(
            np.full((1, grid.shape[1], 1), stride, dtype=np.float32)
        )

    _YOLOX_GRID = np.concatenate(grids, axis=1)
    _YOLOX_EXPANDED_STRIDES = np.concatenate(expanded_strides, axis=1)
    return _YOLOX_GRID, _YOLOX_EXPANDED_STRIDES


def prepare_yolox_input(
    source: Any,
    *,
    cv2_module=None,
) -> tuple[np.ndarray, float]:
    """Convert a BGR frame to the official YOLOX RGB letterbox tensor."""

    image_size = _valid_image_size(source)
    if image_size is None:
        raise ValueError("YOLOX requires a non-empty image")

    if cv2_module is None:
        import cv2 as cv2_module

    image_width, image_height = image_size
    input_width, input_height = YOLOX_INPUT_SIZE
    scale = min(input_width / image_width, input_height / image_height)
    resized_width = max(1, int(image_width * scale))
    resized_height = max(1, int(image_height * scale))
    resized = cv2_module.resize(
        source,
        (resized_width, resized_height),
        interpolation=cv2_module.INTER_LINEAR,
    ).astype(np.float32)
    resized_rgb = resized[:, :, ::-1]

    letterboxed = np.full(
        (input_height, input_width, 3),
        114.0,
        dtype=np.float32,
    )
    letterboxed[:resized_height, :resized_width] = resized_rgb
    blob = np.ascontiguousarray(letterboxed.transpose(2, 0, 1)[np.newaxis])
    return blob, float(scale)


def postprocess_yolox_person_boxes(
    outputs: Any,
    *,
    letterbox_scale: float,
    image_size: tuple[int, int],
    conf: float = PRESENCE_PERSON_DETECTION_CONFIDENCE,
    cv2_module=None,
) -> list[tuple[int, int, int, int]]:
    """Decode YOLOX output and return only NMS-filtered COCO person boxes."""

    if cv2_module is None:
        import cv2 as cv2_module

    predictions = np.asarray(outputs)
    if predictions.ndim == 3 and predictions.shape[0] == 1:
        predictions = predictions[0]
    if predictions.ndim != 2 or predictions.shape[1] < 5 + YOLOX_CLASS_COUNT:
        raise ValueError(f"Unexpected YOLOX output shape: {predictions.shape}")

    grid, expanded_strides = _yolox_grid_and_strides()
    if predictions.shape[0] != grid.shape[1]:
        raise ValueError(
            f"Unexpected YOLOX candidate count: {predictions.shape[0]} "
            f"(expected {grid.shape[1]})"
        )
    if not math.isfinite(float(letterbox_scale)) or letterbox_scale <= 0:
        raise ValueError("YOLOX letterbox scale must be positive")

    decoded = predictions.astype(np.float32, copy=True)
    decoded[:, :2] = (decoded[:, :2] + grid[0]) * expanded_strides[0]
    decoded[:, 2:4] = np.exp(decoded[:, 2:4]) * expanded_strides[0]

    class_scores = decoded[:, 4:5] * decoded[:, 5 : 5 + YOLOX_CLASS_COUNT]
    class_ids = np.argmax(class_scores, axis=1)
    best_scores = np.max(class_scores, axis=1)
    candidate_indices = np.flatnonzero(
        (class_ids == YOLOX_PERSON_CLASS_ID)
        & np.isfinite(best_scores)
        & (best_scores >= float(conf))
    )
    if candidate_indices.size == 0:
        return []

    image_width, image_height = image_size
    if image_width <= 0 or image_height <= 0:
        raise ValueError("YOLOX output image size must be positive")

    boxes_xywh = []
    scores = []
    for index in candidate_indices:
        center_x, center_y, width, height = decoded[index, :4] / letterbox_scale
        x = max(0.0, min(float(image_width), float(center_x - width / 2.0)))
        y = max(0.0, min(float(image_height), float(center_y - height / 2.0)))
        x2 = max(x, min(float(image_width), float(center_x + width / 2.0)))
        y2 = max(y, min(float(image_height), float(center_y + height / 2.0)))
        if x2 <= x or y2 <= y:
            continue
        boxes_xywh.append([x, y, x2 - x, y2 - y])
        scores.append(float(best_scores[index]))

    if not boxes_xywh:
        return []

    kept_indices = cv2_module.dnn.NMSBoxes(
        boxes_xywh,
        scores,
        0.0,
        YOLOX_NMS_THRESHOLD,
    )
    if len(kept_indices) == 0:
        return []

    boxes = []
    for index in np.asarray(kept_indices).reshape(-1):
        x, y, width, height = boxes_xywh[int(index)]
        x1 = max(0, min(image_width - 1, int(round(x))))
        y1 = max(0, min(image_height - 1, int(round(y))))
        x2 = max(x1, min(image_width - 1, int(round(x + width))))
        y2 = max(y1, min(image_height - 1, int(round(y + height))))
        boxes.append((x1, y1, x2, y2))
    return boxes


class OpenCvYoloXPersonDetector:
    """OpenCV DNN wrapper for the bundled OpenCV Zoo YOLOX model."""

    def __init__(self, model_path: str | Path, *, cv2_module=None):
        if cv2_module is None:
            import cv2 as cv2_module

        self._cv2 = cv2_module
        self._net = cv2_module.dnn.readNet(str(model_path))
        self._net.setPreferableBackend(cv2_module.dnn.DNN_BACKEND_OPENCV)
        self._net.setPreferableTarget(cv2_module.dnn.DNN_TARGET_CPU)

    def detect_person_boxes(
        self,
        source: Any,
        conf: float = PRESENCE_PERSON_DETECTION_CONFIDENCE,
    ) -> list[tuple[int, int, int, int]]:
        image_size = _valid_image_size(source)
        if image_size is None:
            return []

        blob, scale = prepare_yolox_input(source, cv2_module=self._cv2)
        self._net.setInput(blob)
        output_names = self._net.getUnconnectedOutLayersNames()
        outputs = self._net.forward(output_names)
        output = outputs[0] if isinstance(outputs, (list, tuple)) else outputs
        return postprocess_yolox_person_boxes(
            output,
            letterbox_scale=scale,
            image_size=image_size,
            conf=conf,
            cv2_module=self._cv2,
        )


def get_person_presence_detector() -> OpenCvYoloXPersonDetector:
    global _PERSON_PRESENCE_DETECTOR
    if _PERSON_PRESENCE_DETECTOR is not None:
        return _PERSON_PRESENCE_DETECTOR

    with _PERSON_PRESENCE_DETECTOR_LOCK:
        if _PERSON_PRESENCE_DETECTOR is None:
            _PERSON_PRESENCE_DETECTOR = OpenCvYoloXPersonDetector(
                resolve_person_presence_model_path()
            )
    return _PERSON_PRESENCE_DETECTOR


def detect_presence_faces(
    source: Any,
    model=None,
    conf: float = PRESENCE_DETECTION_CONFIDENCE,
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


def detect_camera_facing_faces(
    source: Any,
    model=None,
    conf: float = PERSON_DETECTION_CONFIDENCE,
) -> list[Any]:
    return [
        face
        for face in detect_presence_faces(source, model=model, conf=conf)
        if is_roughly_frontal_face(face)
    ]


def detect_presence_count(
    source: Any,
    model=None,
    conf: float = PRESENCE_DETECTION_CONFIDENCE,
    *,
    person_model=None,
) -> int:
    if _valid_image_size(source) is None:
        return 0

    detector_errors = []
    try:
        if detect_presence_faces(source, model=model, conf=conf):
            return 1
    except Exception as exc:
        detector_errors.append(("face", exc))

    try:
        detector = person_model or get_person_presence_detector()
        with _PERSON_PRESENCE_DETECTOR_LOCK:
            person_boxes = detector.detect_person_boxes(
                source,
                conf=PRESENCE_PERSON_DETECTION_CONFIDENCE,
            )
        if person_boxes:
            return 1
    except Exception as exc:
        detector_errors.append(("person", exc))

    if detector_errors:
        failed_detectors = ", ".join(name for name, _ in detector_errors)
        raise PresenceDetectionUnavailable(
            f"Presence detection unavailable because {failed_detectors} detector failed"
        ) from detector_errors[0][1]
    return 0


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

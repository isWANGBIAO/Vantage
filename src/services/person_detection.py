from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


PERSON_CLASS_ID = 0
PERSON_DETECTION_CONFIDENCE = 0.25
PERSON_DETECTION_MODEL = "yolo26m.pt"
FACE_CASCADE_NAME = "haarcascade_frontalface_default.xml"
_YOLO_MODEL = None
_OPENCV_FACE_CASCADE = None


def get_yolo_model():
    global _YOLO_MODEL
    if _YOLO_MODEL is None:
        if not Path(PERSON_DETECTION_MODEL).exists():
            raise FileNotFoundError(f"Missing person detection model: {PERSON_DETECTION_MODEL}")

        from ultralytics import YOLO

        _YOLO_MODEL = YOLO(PERSON_DETECTION_MODEL)
    return _YOLO_MODEL


def count_people_in_result(result) -> int:
    person_count = 0
    for box in result.boxes:
        if int(box.cls[0]) == PERSON_CLASS_ID:
            person_count += 1
    return person_count


def should_use_opencv_face_presence_detector(platform: str | None = None) -> bool:
    return (platform or sys.platform) == "darwin"


def _resolve_opencv_face_cascade_path(cv2_module) -> Path:
    candidate_paths = []

    configured_path = os.environ.get("VANTAGE_FACE_CASCADE_PATH")
    if configured_path:
        candidate_paths.append(Path(configured_path))

    meipass_root = getattr(sys, "_MEIPASS", None)
    if meipass_root:
        candidate_paths.append(Path(meipass_root) / "opencv-data" / FACE_CASCADE_NAME)

    executable_parent = Path(sys.executable).resolve().parent
    candidate_paths.extend(
        [
            executable_parent / "_internal" / "opencv-data" / FACE_CASCADE_NAME,
            executable_parent / "opencv-data" / FACE_CASCADE_NAME,
            Path(cv2_module.data.haarcascades) / FACE_CASCADE_NAME,
        ]
    )

    for candidate_path in candidate_paths:
        if candidate_path.exists():
            return candidate_path.resolve()

    raise FileNotFoundError("OpenCV face cascade not found in packaged runtime or local OpenCV data paths.")


def get_opencv_face_cascade():
    global _OPENCV_FACE_CASCADE
    if _OPENCV_FACE_CASCADE is None:
        import cv2

        cascade_path = _resolve_opencv_face_cascade_path(cv2)
        cascade = cv2.CascadeClassifier(str(cascade_path))
        if cascade.empty():
            raise RuntimeError(f"Failed to load OpenCV face cascade: {cascade_path}")
        _OPENCV_FACE_CASCADE = cascade
    return _OPENCV_FACE_CASCADE


def detect_face_count_with_opencv(source: Any, conf: float = PERSON_DETECTION_CONFIDENCE) -> int:
    if source is None or getattr(source, "size", 0) == 0:
        return 0

    import cv2

    cascade = get_opencv_face_cascade()
    gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    h, w = source.shape[:2]
    min_side = max(32, int(min(h, w) * 0.12))
    min_neighbors = max(3, int(round(3 + (float(conf) * 4))))
    detections = cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=min_neighbors,
        minSize=(min_side, min_side),
    )
    return int(len(detections))


def detect_person_counts(sources: list[Any], model=None, conf: float = PERSON_DETECTION_CONFIDENCE) -> list[int]:
    if model is None and should_use_opencv_face_presence_detector():
        return [detect_face_count_with_opencv(source, conf=conf) for source in sources]

    model = model or get_yolo_model()
    results = model.predict(source=sources, verbose=False, conf=conf)
    return [count_people_in_result(result) for result in results]


def detect_person_count(source: Any, model=None, conf: float = PERSON_DETECTION_CONFIDENCE) -> int:
    return detect_person_counts([source], model=model, conf=conf)[0]

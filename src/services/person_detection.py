from __future__ import annotations

from typing import Any


PERSON_CLASS_ID = 0
PERSON_DETECTION_CONFIDENCE = 0.25
PERSON_DETECTION_MODEL = "yolo26m.pt"
_YOLO_MODEL = None


def get_yolo_model():
    global _YOLO_MODEL
    if _YOLO_MODEL is None:
        from ultralytics import YOLO

        _YOLO_MODEL = YOLO(PERSON_DETECTION_MODEL)
    return _YOLO_MODEL


def detect_person_count(source: Any, model=None, conf: float = PERSON_DETECTION_CONFIDENCE) -> int:
    model = model or get_yolo_model()
    results = model.predict(source=source, verbose=False, conf=conf)
    person_count = 0
    for result in results:
        for box in result.boxes:
            if int(box.cls[0]) == PERSON_CLASS_ID:
                person_count += 1
    return person_count

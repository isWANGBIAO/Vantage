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


def count_people_in_result(result) -> int:
    person_count = 0
    for box in result.boxes:
        if int(box.cls[0]) == PERSON_CLASS_ID:
            person_count += 1
    return person_count


def detect_person_counts(sources: list[Any], model=None, conf: float = PERSON_DETECTION_CONFIDENCE) -> list[int]:
    model = model or get_yolo_model()
    results = model.predict(source=sources, verbose=False, conf=conf)
    return [count_people_in_result(result) for result in results]


def detect_person_count(source: Any, model=None, conf: float = PERSON_DETECTION_CONFIDENCE) -> int:
    return detect_person_counts([source], model=model, conf=conf)[0]

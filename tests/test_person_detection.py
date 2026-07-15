import unittest
from unittest.mock import patch

import numpy as np

from src.services import person_detection


def _face_row(
    *,
    x=10.0,
    y=20.0,
    width=100.0,
    height=120.0,
    nose_x=60.0,
    right_eye_y=55.0,
    left_eye_y=54.0,
    confidence=0.96,
):
    return np.array(
        [
            x,
            y,
            width,
            height,
            40.0,
            right_eye_y,
            80.0,
            left_eye_y,
            nose_x,
            82.0,
            45.0,
            110.0,
            75.0,
            109.0,
            confidence,
        ],
        dtype=np.float32,
    )


def _slightly_turned_face_row(*, confidence=0.91):
    return np.array(
        [
            207.79,
            182.53,
            145.94,
            206.92,
            271.64,
            269.45,
            328.47,
            276.10,
            309.69,
            312.88,
            270.93,
            342.16,
            311.31,
            348.41,
            confidence,
        ],
        dtype=np.float32,
    )


class _FakeFaceDetector:
    def __init__(self, faces):
        self.faces = faces
        self.input_sizes = []
        self.score_thresholds = []
        self.detected_images = []
        self.score_threshold = 0.0

    def setInputSize(self, input_size):
        self.input_sizes.append(input_size)

    def setScoreThreshold(self, score_threshold):
        self.score_thresholds.append(score_threshold)
        self.score_threshold = score_threshold

    def detect(self, image):
        self.detected_images.append(image)
        if self.faces is None:
            return 1, None
        faces = np.asarray(self.faces)
        matching_faces = faces[faces[:, 14] >= self.score_threshold]
        return 1, matching_faces if len(matching_faces) else None


class _RawFaceDetector:
    """Return malformed YuNet rows without test-double pre-validation."""

    def __init__(self, faces):
        self.faces = faces
        self.input_sizes = []
        self.score_thresholds = []
        self.detected_images = []

    def setInputSize(self, input_size):
        self.input_sizes.append(input_size)

    def setScoreThreshold(self, score_threshold):
        self.score_thresholds.append(score_threshold)

    def detect(self, image):
        self.detected_images.append(image)
        return 1, self.faces


class _FailingFaceDetector(_FakeFaceDetector):
    def __init__(self, error):
        super().__init__(None)
        self.error = error

    def detect(self, image):
        self.detected_images.append(image)
        raise self.error


class PersonDetectionTests(unittest.TestCase):
    def test_frontal_geometry_accepts_balanced_landmarks(self):
        self.assertTrue(person_detection.is_roughly_frontal_face(_face_row()))

    def test_frontal_geometry_accepts_a_slightly_turned_but_visible_face(self):
        self.assertTrue(person_detection.is_roughly_frontal_face(_slightly_turned_face_row()))

    def test_frontal_geometry_rejects_side_facing_landmarks_even_with_both_eyes(self):
        self.assertFalse(person_detection.is_roughly_frontal_face(_face_row(nose_x=86.0)))

    def test_frontal_geometry_rejects_strongly_tilted_eye_line(self):
        self.assertFalse(
            person_detection.is_roughly_frontal_face(
                _face_row(right_eye_y=48.0, left_eye_y=72.0)
            )
        )

    def test_detect_person_count_keeps_only_roughly_camera_facing_faces(self):
        detector = _FakeFaceDetector(
            np.vstack([_face_row(), _face_row(nose_x=86.0)])
        )
        frame = np.zeros((180, 320, 3), dtype=np.uint8)

        count = person_detection.detect_person_count(frame, model=detector, conf=0.88)

        self.assertEqual(count, 1)
        self.assertEqual(detector.input_sizes, [(320, 180)])
        self.assertEqual(detector.score_thresholds, [0.88])
        self.assertIs(detector.detected_images[0], frame)

    def test_large_non_frontal_face_at_moderate_confidence_is_presence_only(self):
        detector = _FakeFaceDetector(
            np.vstack([_face_row(nose_x=86.0, confidence=0.55)])
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        presence_count = person_detection.detect_presence_count(frame, model=detector)
        camera_facing_count = person_detection.detect_person_count(frame, model=detector)

        self.assertEqual(presence_count, 1)
        self.assertEqual(camera_facing_count, 0)
        self.assertEqual(
            detector.score_thresholds,
            [
                person_detection.PRESENCE_DETECTION_CONFIDENCE,
                person_detection.PERSON_DETECTION_CONFIDENCE,
            ],
        )

    def test_small_background_face_is_absent_and_has_no_foreground_box(self):
        detector = _FakeFaceDetector(
            np.vstack([_face_row(width=32, height=32, confidence=0.96)])
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        count = person_detection.detect_presence_count(frame, model=detector)
        boxes = person_detection.detect_foreground_presence_face_boxes(
            frame, model=detector
        )

        self.assertEqual(count, 0)
        self.assertEqual(boxes, [])

    def test_foreground_area_threshold_includes_exact_boundary(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        accepted = _FakeFaceDetector(np.vstack([_face_row(width=48, height=32)]))
        rejected = _FakeFaceDetector(np.vstack([_face_row(width=47, height=32)]))

        self.assertEqual(
            person_detection.detect_foreground_presence_face_boxes(
                frame, model=accepted
            ),
            [(10, 20, 58, 52)],
        )
        self.assertEqual(
            person_detection.detect_foreground_presence_face_boxes(
                frame, model=rejected
            ),
            [],
        )

    def test_foreground_area_uses_clipped_box(self):
        detector = _FakeFaceDetector(
            np.vstack([_face_row(x=-20, y=0, width=60, height=30)])
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        boxes = person_detection.detect_foreground_presence_face_boxes(
            frame, model=detector
        )

        self.assertEqual(boxes, [])

    def test_foreground_selector_returns_only_largest_qualifying_face(self):
        detector = _FakeFaceDetector(
            np.vstack(
                [
                    _face_row(x=20, y=20, width=32, height=32),
                    _face_row(x=100, y=80, width=120, height=100),
                    _face_row(x=400, y=200, width=80, height=80),
                ]
            )
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        boxes = person_detection.detect_foreground_presence_face_boxes(
            frame, model=detector
        )

        self.assertEqual(boxes, [(100, 80, 220, 180)])

    def test_multiple_qualifying_faces_choose_largest_area(self):
        detector = _FakeFaceDetector(
            np.vstack(
                [
                    _face_row(x=50, y=60, width=80, height=80),
                    _face_row(x=200, y=100, width=100, height=70),
                ]
            )
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        boxes = person_detection.detect_foreground_presence_face_boxes(
            frame, model=detector
        )

        self.assertEqual(boxes, [(200, 100, 300, 170)])

    def test_invalid_raw_yunet_rows_make_presence_unavailable(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        invalid_rows = [
            np.zeros(14, dtype=np.float32),
            np.array([10, 20, 100, 120, *([0] * 10), np.nan], dtype=np.float32),
            np.array([10, 20, 100, 120, *([0] * 10), np.inf], dtype=np.float32),
            _face_row(width=0),
            _face_row(height=-1),
        ]

        for row in invalid_rows:
            with self.subTest(row=row):
                detector = _RawFaceDetector([row])
                with self.assertRaises(person_detection.PresenceDetectionUnavailable):
                    person_detection.detect_presence_count(frame, model=detector)

    def test_face_detector_failure_makes_presence_unavailable(self):
        detector = _FailingFaceDetector(RuntimeError("face unavailable"))
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with self.assertRaises(person_detection.PresenceDetectionUnavailable):
            person_detection.detect_presence_count(frame, model=detector)

    def test_non_frontal_face_is_not_in_strict_camera_facing_analysis(self):
        detector = _FakeFaceDetector(
            np.vstack([_face_row(nose_x=86.0, confidence=0.55)])
        )
        frame = np.zeros((180, 320, 3), dtype=np.uint8)

        camera_facing_faces = person_detection.detect_camera_facing_faces(
            frame,
            model=detector,
            conf=person_detection.PRESENCE_DETECTION_CONFIDENCE,
        )

        self.assertEqual(camera_facing_faces, [])

    def test_detect_person_counts_retains_compatible_batch_function_name(self):
        detector = _FakeFaceDetector(np.vstack([_face_row()]))
        frames = [
            np.zeros((120, 160, 3), dtype=np.uint8),
            np.zeros((240, 320, 3), dtype=np.uint8),
        ]

        counts = person_detection.detect_person_counts(frames, model=detector)

        self.assertEqual(counts, [1, 1])
        self.assertEqual(detector.input_sizes, [(160, 120), (320, 240)])

    def test_detect_face_boxes_converts_yunet_width_and_height_to_corners(self):
        detector = _FakeFaceDetector(np.vstack([_face_row()]))
        frame = np.zeros((180, 320, 3), dtype=np.uint8)

        boxes = person_detection.detect_face_boxes(frame, model=detector)

        self.assertEqual(boxes, [(10, 20, 110, 140)])

    def test_empty_frame_returns_no_detection_without_calling_model(self):
        detector = _FakeFaceDetector(np.vstack([_face_row()]))

        count = person_detection.detect_person_count(None, model=detector)

        self.assertEqual(count, 0)
        self.assertEqual(detector.detected_images, [])

    def test_batch_of_empty_frames_does_not_load_model(self):
        with patch.object(
            person_detection,
            "get_face_detector",
            side_effect=AssertionError("empty frames should not load the model"),
        ):
            counts = person_detection.detect_person_counts([None, None])

        self.assertEqual(counts, [0, 0])

    def test_empty_presence_frame_does_not_load_face_detector(self):
        with patch.object(
            person_detection,
            "get_face_detector",
            side_effect=AssertionError("empty frame should not load face detector"),
        ):
            count = person_detection.detect_presence_count(None)

        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()

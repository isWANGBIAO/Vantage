import unittest
from unittest.mock import patch

import numpy as np

from src.services import person_detection


def _face_row(
    *,
    nose_x=60.0,
    right_eye_y=55.0,
    left_eye_y=54.0,
    confidence=0.96,
):
    return np.array(
        [
            10.0,
            20.0,
            100.0,
            120.0,
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


class _FakePersonDetector:
    def __init__(self, boxes=None, error=None):
        self.boxes = list(boxes or [])
        self.error = error
        self.calls = []

    def detect_person_boxes(self, image, conf):
        self.calls.append((image, conf))
        if self.error is not None:
            raise self.error
        return self.boxes


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

    def test_frontal_geometry_rejects_side_facing_landmarks_even_when_both_eyes_are_visible(self):
        self.assertFalse(person_detection.is_roughly_frontal_face(_face_row(nose_x=86.0)))

    def test_frontal_geometry_rejects_strongly_tilted_eye_line(self):
        self.assertFalse(
            person_detection.is_roughly_frontal_face(
                _face_row(right_eye_y=48.0, left_eye_y=72.0)
            )
        )

    def test_detect_person_count_keeps_only_roughly_camera_facing_faces(self):
        faces = np.vstack([_face_row(), _face_row(nose_x=86.0)])
        detector = _FakeFaceDetector(faces)
        frame = np.zeros((180, 320, 3), dtype=np.uint8)

        count = person_detection.detect_person_count(frame, model=detector, conf=0.88)

        self.assertEqual(count, 1)
        self.assertEqual(detector.input_sizes, [(320, 180)])
        self.assertEqual(detector.score_thresholds, [0.88])
        self.assertIs(detector.detected_images[0], frame)

    def test_presence_accepts_moderate_confidence_slightly_turned_face(self):
        detector = _FakeFaceDetector(
            np.vstack([_slightly_turned_face_row(confidence=0.55)])
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

    def test_presence_accepts_body_when_face_is_not_visible(self):
        face_detector = _FakeFaceDetector(None)
        person_detector = _FakePersonDetector([(20, 30, 120, 220)])
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        presence_count = person_detection.detect_presence_count(
            frame,
            model=face_detector,
            person_model=person_detector,
        )

        self.assertEqual(presence_count, 1)
        self.assertEqual(len(person_detector.calls), 1)
        self.assertIs(person_detector.calls[0][0], frame)
        self.assertEqual(
            person_detector.calls[0][1],
            person_detection.PRESENCE_PERSON_DETECTION_CONFIDENCE,
        )

    def test_presence_does_not_double_count_face_and_body_signals(self):
        face_detector = _FakeFaceDetector(np.vstack([_face_row()]))
        person_detector = _FakePersonDetector([(20, 30, 120, 220)])
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        presence_count = person_detection.detect_presence_count(
            frame,
            model=face_detector,
            person_model=person_detector,
        )

        self.assertEqual(presence_count, 1)
        self.assertEqual(person_detector.calls, [])

    def test_presence_accepts_body_when_face_detector_fails(self):
        face_detector = _FailingFaceDetector(RuntimeError("face unavailable"))
        person_detector = _FakePersonDetector([(20, 30, 120, 220)])
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        presence_count = person_detection.detect_presence_count(
            frame,
            model=face_detector,
            person_model=person_detector,
        )

        self.assertEqual(presence_count, 1)

    def test_presence_is_unavailable_when_face_is_empty_and_person_detector_fails(self):
        face_detector = _FakeFaceDetector(None)
        person_detector = _FakePersonDetector(error=RuntimeError("person unavailable"))
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with self.assertRaises(person_detection.PresenceDetectionUnavailable):
            person_detection.detect_presence_count(
                frame,
                model=face_detector,
                person_model=person_detector,
            )

    def test_presence_is_unavailable_when_face_fails_and_body_is_empty(self):
        face_detector = _FailingFaceDetector(RuntimeError("face unavailable"))
        person_detector = _FakePersonDetector([])
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with self.assertRaises(person_detection.PresenceDetectionUnavailable):
            person_detection.detect_presence_count(
                frame,
                model=face_detector,
                person_model=person_detector,
            )

    def test_presence_is_absent_only_when_both_detectors_succeed_without_a_match(self):
        face_detector = _FakeFaceDetector(None)
        person_detector = _FakePersonDetector([])
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        presence_count = person_detection.detect_presence_count(
            frame,
            model=face_detector,
            person_model=person_detector,
        )

        self.assertEqual(presence_count, 0)

    def test_non_frontal_face_is_presence_but_not_camera_facing_at_same_threshold(self):
        detector = _FakeFaceDetector(
            np.vstack([_face_row(nose_x=86.0, confidence=0.55)])
        )
        frame = np.zeros((180, 320, 3), dtype=np.uint8)

        presence_faces = person_detection.detect_presence_faces(frame, model=detector)
        camera_facing_faces = person_detection.detect_camera_facing_faces(
            frame,
            model=detector,
            conf=person_detection.PRESENCE_DETECTION_CONFIDENCE,
        )

        self.assertEqual(len(presence_faces), 1)
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

    def test_empty_presence_frame_does_not_load_either_detector(self):
        with patch.object(
            person_detection,
            "get_face_detector",
            side_effect=AssertionError("empty frame should not load face detector"),
        ), patch.object(
            person_detection,
            "get_person_presence_detector",
            side_effect=AssertionError("empty frame should not load person detector"),
        ):
            count = person_detection.detect_presence_count(None)

        self.assertEqual(count, 0)

    def test_yolox_preprocessing_letterboxes_bgr_as_rgb_nchw(self):
        frame = np.full((2, 4, 3), (10, 20, 30), dtype=np.uint8)

        blob, scale = person_detection.prepare_yolox_input(frame)

        self.assertEqual(blob.shape, (1, 3, 640, 640))
        self.assertEqual(blob.dtype, np.float32)
        np.testing.assert_array_equal(blob[0, :, 0, 0], [30.0, 20.0, 10.0])
        np.testing.assert_array_equal(blob[0, :, -1, -1], [114.0, 114.0, 114.0])
        self.assertEqual(scale, 160.0)

    def test_yolox_postprocessing_keeps_only_person_above_threshold(self):
        predictions = np.zeros((1, 8400, 85), dtype=np.float32)
        predictions[0, 0, 4] = 1.0
        predictions[0, 0, 5] = 0.51
        predictions[0, 1, 4] = 1.0
        predictions[0, 1, 5] = 0.49
        predictions[0, 2, 4] = 1.0
        predictions[0, 2, 5] = 0.60
        predictions[0, 2, 6] = 0.90

        boxes = person_detection.postprocess_yolox_person_boxes(
            predictions,
            letterbox_scale=1.0,
            image_size=(640, 640),
            conf=person_detection.PRESENCE_PERSON_DETECTION_CONFIDENCE,
        )

        self.assertEqual(len(boxes), 1)
        self.assertEqual(len(boxes[0]), 4)


if __name__ == "__main__":
    unittest.main()

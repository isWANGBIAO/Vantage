import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.services.face_analysis_pipeline import (
    AnalysisConfig,
    FaceParser,
    analyze_image_data,
    build_face_report,
    compute_trend_series,
    filter_report_outlier_points,
    filter_stable_trend_points,
    normalize_dark_circle_score,
    plot_trend,
    trend_axis_date_format,
)


class FakeDetector:
    def __init__(self, bbox=None):
        self.bbox = bbox

    def detect(self, image_bgr):
        return self.bbox


class FakeParser:
    def infer(self, image_bgr):
        h, w = image_bgr.shape[:2]
        parsing_map = np.zeros((h, w), dtype=np.uint8)

        # Skin background
        parsing_map[10:h - 10, 10:w - 10] = 1

        # Eye masks
        parsing_map[22:30, 20:36] = 4
        parsing_map[22:30, 64:80] = 5

        return parsing_map, image_bgr


class FakeParserWithoutEyes(FakeParser):
    def infer(self, image_bgr):
        h, w = image_bgr.shape[:2]
        parsing_map = np.zeros((h, w), dtype=np.uint8)
        parsing_map[10:h - 10, 10:w - 10] = 1
        return parsing_map, image_bgr

    def infer_fallback(self, image_bgr):
        parsing_map, _ = super().infer(image_bgr)
        return parsing_map


class FakeParserWithSparsePrimarySkin(FakeParserWithoutEyes):
    def infer(self, image_bgr):
        h, w = image_bgr.shape[:2]
        parsing_map = np.zeros((h, w), dtype=np.uint8)
        parsing_map[40:55, 40:55] = 1
        return parsing_map, image_bgr


class FaceAnalysisPipelineTests(unittest.TestCase):
    def test_normalize_dark_circle_score_maps_raw_values_to_0_100(self):
        self.assertIsNone(normalize_dark_circle_score(None))
        self.assertEqual(normalize_dark_circle_score(0.0), 0.0)
        self.assertEqual(normalize_dark_circle_score(1.23), 12.3)
        self.assertEqual(normalize_dark_circle_score(17.0), 100.0)

    def make_test_image(self):
        image = np.full((100, 100, 3), 90, dtype=np.uint8)

        # Left under-eye dark patch / cheek bright patch
        image[30:36, 20:36] = (35, 35, 35)
        image[44:48, 22:34] = (185, 185, 185)

        # Right under-eye dark patch / cheek bright patch
        image[30:36, 64:80] = (45, 45, 45)
        image[44:48, 66:78] = (190, 190, 190)
        return image

    def make_warm_lit_test_image(self):
        image = self.make_test_image().astype(np.int16)
        image[:, :, 2] = np.clip(image[:, :, 2] + 100, 0, 255)
        image[:, :, 1] = np.clip(image[:, :, 1] + 55, 0, 255)
        image[:, :, 0] = np.clip(image[:, :, 0] - 35, 0, 255)
        return image.astype(np.uint8)

    def test_analyze_image_data_rejects_missing_face_without_zero_score(self):
        result = analyze_image_data(
            self.make_test_image(),
            detector=FakeDetector(bbox=None),
            parser=FakeParser(),
            source_path="photo.jpg",
            observed_at=datetime(2026, 3, 11, 12, 0, 0),
        )

        self.assertFalse(result["passed"])
        self.assertIn("NoFace", result["fail_reason"])
        self.assertIsNone(result["score"])
        self.assertIsNone(result["score_left"])
        self.assertIsNone(result["score_right"])

    def test_analyze_image_data_scores_from_detected_face_crop(self):
        result = analyze_image_data(
            self.make_test_image(),
            detector=FakeDetector(bbox=(0, 0, 100, 100)),
            parser=FakeParser(),
            source_path="photo.jpg",
            observed_at=datetime(2026, 3, 11, 12, 5, 0),
            config=AnalysisConfig(min_face_size=80),
        )

        self.assertTrue(result["passed"])
        self.assertGreater(result["score_left"], 0)
        self.assertGreater(result["score_right"], 0)
        self.assertGreater(result["score"], 0)
        self.assertEqual(result["fail_reason"], [])

    def test_analyze_image_data_exposes_feature_breakdown_and_lighting_quality(self):
        result = analyze_image_data(
            self.make_test_image(),
            detector=FakeDetector(bbox=(0, 0, 100, 100)),
            parser=FakeParser(),
            source_path="photo.jpg",
            observed_at=datetime(2026, 3, 11, 12, 6, 0),
            config=AnalysisConfig(min_face_size=80),
        )

        self.assertTrue(result["passed"])
        self.assertIn("features", result)
        self.assertIn("quality", result)
        self.assertGreater(result["features"]["relative_luminance_left"], 0)
        self.assertGreaterEqual(result["quality"]["lighting_confidence"], 0.0)
        self.assertLessEqual(result["quality"]["lighting_confidence"], 1.0)

    def test_analyze_image_data_reduces_warm_lighting_score_drift(self):
        base_result = analyze_image_data(
            self.make_test_image(),
            detector=FakeDetector(bbox=(0, 0, 100, 100)),
            parser=FakeParser(),
            source_path="base.jpg",
            observed_at=datetime(2026, 3, 11, 12, 6, 0),
            config=AnalysisConfig(min_face_size=80),
        )
        warm_result = analyze_image_data(
            self.make_warm_lit_test_image(),
            detector=FakeDetector(bbox=(0, 0, 100, 100)),
            parser=FakeParser(),
            source_path="warm.jpg",
            observed_at=datetime(2026, 3, 11, 12, 6, 5),
            config=AnalysisConfig(min_face_size=80),
        )

        self.assertTrue(base_result["passed"])
        self.assertTrue(warm_result["passed"])
        self.assertLess(abs(base_result["score"] - warm_result["score"]), 4.0)

    def test_build_face_report_ignores_failed_rows(self):
        results = [
            {
                "path": "invalid.jpg",
                "datetime": "2026-03-11 10:00:00",
                "timestamp": datetime(2026, 3, 11, 10, 0, 0).timestamp(),
                "passed": False,
                "score": None,
                "fail_reason": ["NoFace"],
            },
            {
                "path": "light.jpg",
                "datetime": "2026-03-11 11:00:00",
                "timestamp": datetime(2026, 3, 11, 11, 0, 0).timestamp(),
                "passed": True,
                "score": 3.2,
                "score_left": 3.1,
                "score_right": 3.3,
                "fail_reason": [],
            },
            {
                "path": "heavy.jpg",
                "datetime": "2026-03-11 12:00:00",
                "timestamp": datetime(2026, 3, 11, 12, 0, 0).timestamp(),
                "passed": True,
                "score": 8.4,
                "score_left": 8.0,
                "score_right": 8.8,
                "fail_reason": [],
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            report = build_face_report(results, output_dir)

        self.assertEqual(report["count"], 2)
        self.assertEqual(report["quality"]["failed"], 1)
        self.assertEqual(report["quality"]["fail_reason_counts"]["NoFace"], 1)
        self.assertEqual(report["lightest"]["path"], "light.jpg")
        self.assertEqual(report["heaviest"]["path"], "heavy.jpg")
        self.assertTrue(report["trend_plot_path"].endswith("dark_circles_trend.png"))
        self.assertEqual(set(report["trend_views"].keys()), {"day", "week", "month", "all"})
        self.assertEqual(report["trend_views"]["day"]["label"], "最近24小时")
        self.assertEqual(report["trend_views"]["all"]["label"], "全部历史")
        self.assertEqual([point["score"] for point in report["trend_views"]["day"]["points"]], [3.2, 8.4])
        self.assertEqual([point["score"] for point in report["trend_views"]["all"]["points"]], [5.8])

    def test_build_face_report_builds_windowed_trend_views_from_latest_sample(self):
        results = [
            {
                "path": "old.jpg",
                "datetime": "2026-02-01 08:00:00",
                "timestamp": datetime(2026, 2, 1, 8, 0, 0).timestamp(),
                "passed": True,
                "score": 2.0,
                "score_left": 2.0,
                "score_right": 2.0,
                "fail_reason": [],
            },
            {
                "path": "month-a.jpg",
                "datetime": "2026-03-01 08:00:00",
                "timestamp": datetime(2026, 3, 1, 8, 0, 0).timestamp(),
                "passed": True,
                "score": 4.0,
                "score_left": 4.0,
                "score_right": 4.0,
                "fail_reason": [],
            },
            {
                "path": "week-a.jpg",
                "datetime": "2026-03-10 10:00:00",
                "timestamp": datetime(2026, 3, 10, 10, 0, 0).timestamp(),
                "passed": True,
                "score": 5.0,
                "score_left": 5.0,
                "score_right": 5.0,
                "fail_reason": [],
            },
            {
                "path": "week-b.jpg",
                "datetime": "2026-03-10 18:00:00",
                "timestamp": datetime(2026, 3, 10, 18, 0, 0).timestamp(),
                "passed": True,
                "score": 7.0,
                "score_left": 7.0,
                "score_right": 7.0,
                "fail_reason": [],
            },
            {
                "path": "day-a.jpg",
                "datetime": "2026-03-12 15:00:00",
                "timestamp": datetime(2026, 3, 12, 15, 0, 0).timestamp(),
                "passed": True,
                "score": 8.0,
                "score_left": 8.0,
                "score_right": 8.0,
                "fail_reason": [],
            },
            {
                "path": "day-b.jpg",
                "datetime": "2026-03-13 10:00:00",
                "timestamp": datetime(2026, 3, 13, 10, 0, 0).timestamp(),
                "passed": True,
                "score": 10.0,
                "score_left": 10.0,
                "score_right": 10.0,
                "fail_reason": [],
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            report = build_face_report(results, Path(tmpdir))

        day_scores = [point["score"] for point in report["trend_views"]["day"]["points"]]
        week_scores = [point["score"] for point in report["trend_views"]["week"]["points"]]
        month_scores = [point["score"] for point in report["trend_views"]["month"]["points"]]
        all_scores = [point["score"] for point in report["trend_views"]["all"]["points"]]

        self.assertEqual(day_scores, [8.0, 10.0])
        self.assertEqual(week_scores, [6.0, 8.0, 10.0])
        self.assertEqual(month_scores, [4.0, 6.0, 8.0, 10.0])
        self.assertEqual(all_scores, [2.0, 4.0, 6.0, 8.0, 10.0])

    def test_plot_trend_only_keeps_sample_moving_average_curve(self):
        results = [
            {"datetime": "2026-03-12 10:00:00", "score": 5.0},
            {"datetime": "2026-03-12 10:05:00", "score": 7.0},
            {"datetime": "2026-03-12 10:10:00", "score": 3.0},
            {"datetime": "2026-03-12 10:15:00", "score": 9.0},
        ]

        with tempfile.TemporaryDirectory() as tmpdir, patch("src.services.face_analysis_pipeline.plt.plot") as plot_mock:
            plot_trend(results, Path(tmpdir))

        labels = [kwargs.get("label") for _, kwargs in plot_mock.call_args_list]
        self.assertIn("Sample Moving Average", labels)
        self.assertNotIn("14-Day Trend", labels)
        sample_call = next(kwargs for _, kwargs in plot_mock.call_args_list if kwargs.get("label") == "Sample Moving Average")
        self.assertEqual(sample_call.get("color"), "#E15759")

    def test_trend_axis_date_format_uses_time_for_single_day(self):
        results = [
            {"datetime": "2026-03-12 10:00:00", "score": 5.0},
            {"datetime": "2026-03-12 10:05:00", "score": 7.0},
        ]

        self.assertEqual(trend_axis_date_format(results), "%H:%M")

    def test_trend_axis_date_format_uses_date_for_multiple_days(self):
        results = [
            {"datetime": "2026-03-11 23:55:00", "score": 5.0},
            {"datetime": "2026-03-12 00:05:00", "score": 7.0},
        ]

        self.assertEqual(trend_axis_date_format(results), "%Y-%m-%d")

    def test_compute_trend_series_uses_time_window_and_breaks_large_gaps(self):
        results = [
            {"datetime": "2026-03-12 00:00:00", "score": 10.0},
            {"datetime": "2026-03-12 00:10:00", "score": 20.0},
            {"datetime": "2026-03-12 00:20:00", "score": 30.0},
            {"datetime": "2026-03-12 02:00:00", "score": 30.0},
            {"datetime": "2026-03-12 02:10:00", "score": 50.0},
            {"datetime": "2026-03-12 02:20:00", "score": 40.0},
        ]

        dates, smooth = compute_trend_series(results)

        self.assertEqual(len(dates), 6)
        self.assertTrue(np.isnan(smooth.iloc[0]))
        self.assertAlmostEqual(float(smooth.iloc[1]), 20.0)
        self.assertTrue(np.isnan(smooth.iloc[2]))
        self.assertTrue(np.isnan(smooth.iloc[3]))
        self.assertAlmostEqual(float(smooth.iloc[4]), 40.0)
        self.assertTrue(np.isnan(smooth.iloc[5]))

    def test_plot_trend_title_uses_valid_samples(self):
        results = [
            {"datetime": "2026-03-12 10:00:00", "score": 5.0},
            {"datetime": "2026-03-12 10:05:00", "score": 7.0},
        ]

        with tempfile.TemporaryDirectory() as tmpdir, patch("src.services.face_analysis_pipeline.plt.title") as title_mock:
            plot_trend(results, Path(tmpdir))

        title_mock.assert_called_once_with("Dark Circle Severity Trend (Valid Samples=2)")

    def test_filter_stable_trend_points_removes_lr_gap_and_isolated_spikes(self):
        results = [
            {
                "datetime": "2026-03-12 10:00:00",
                "score": 30.0,
                "score_left": 31.0,
                "score_right": 29.0,
                "passed": True,
            },
            {
                "datetime": "2026-03-12 10:05:00",
                "score": 31.0,
                "score_left": 30.0,
                "score_right": 32.0,
                "passed": True,
            },
            {
                "datetime": "2026-03-12 10:10:00",
                "score": 80.0,
                "score_left": 120.0,
                "score_right": 40.0,
                "passed": True,
            },
            {
                "datetime": "2026-03-12 10:15:00",
                "score": 29.5,
                "score_left": 29.0,
                "score_right": 30.0,
                "passed": True,
            },
            {
                "datetime": "2026-03-12 10:20:00",
                "score": 5.0,
                "score_left": 5.0,
                "score_right": 5.0,
                "passed": True,
            },
            {
                "datetime": "2026-03-12 10:25:00",
                "score": 30.5,
                "score_left": 30.0,
                "score_right": 31.0,
                "passed": True,
            },
        ]

        filtered = filter_stable_trend_points(results)
        scores = [row["score"] for row in filtered]

        self.assertEqual(scores, [30.0, 31.0, 29.5, 30.5])

    def test_filter_report_outlier_points_removes_isolated_high_and_low_spikes(self):
        base_time = datetime(2026, 3, 12, 10, 0, 0)
        results = [
            {
                "path": f"sample-{index}.jpg",
                "datetime": (base_time.replace(minute=index * 5)).strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp": (base_time.replace(minute=index * 5)).timestamp(),
                "score": score,
                "score_left": score - 1,
                "score_right": score + 1,
                "passed": True,
                "fail_reason": [],
            }
            for index, score in enumerate([30.0, 31.0, 66.0, 30.5, 29.8, 4.0, 30.2, 31.1])
        ]

        filtered = filter_report_outlier_points(results)

        self.assertEqual([row["score"] for row in filtered], [30.0, 31.0, 30.5, 29.8, 30.2, 31.1])

    def test_filter_report_outlier_points_keeps_consistent_rise(self):
        base_time = datetime(2026, 3, 12, 14, 0, 0)
        results = [
            {
                "path": f"rise-{index}.jpg",
                "datetime": (base_time.replace(minute=index * 5)).strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp": (base_time.replace(minute=index * 5)).timestamp(),
                "score": score,
                "score_left": score - 0.8,
                "score_right": score + 0.8,
                "passed": True,
                "fail_reason": [],
            }
            for index, score in enumerate([29.0, 31.0, 34.0, 37.0, 39.0])
        ]

        filtered = filter_report_outlier_points(results)

        self.assertEqual([row["score"] for row in filtered], [29.0, 31.0, 34.0, 37.0, 39.0])

    def test_build_face_report_ignores_report_outliers_for_extremes_and_trends(self):
        base_time = datetime(2026, 3, 12, 18, 0, 0)
        results = [
            {
                "path": "steady-1.jpg",
                "datetime": base_time.strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp": base_time.timestamp(),
                "passed": True,
                "score": 30.0,
                "score_left": 29.0,
                "score_right": 31.0,
                "fail_reason": [],
            },
            {
                "path": "spike-high.jpg",
                "datetime": datetime(2026, 3, 12, 18, 5, 0).strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp": datetime(2026, 3, 12, 18, 5, 0).timestamp(),
                "passed": True,
                "score": 66.0,
                "score_left": 65.0,
                "score_right": 67.0,
                "fail_reason": [],
            },
            {
                "path": "steady-2.jpg",
                "datetime": datetime(2026, 3, 12, 18, 10, 0).strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp": datetime(2026, 3, 12, 18, 10, 0).timestamp(),
                "passed": True,
                "score": 31.0,
                "score_left": 30.0,
                "score_right": 32.0,
                "fail_reason": [],
            },
            {
                "path": "spike-low.jpg",
                "datetime": datetime(2026, 3, 12, 18, 15, 0).strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp": datetime(2026, 3, 12, 18, 15, 0).timestamp(),
                "passed": True,
                "score": 4.0,
                "score_left": 3.5,
                "score_right": 4.5,
                "fail_reason": [],
            },
            {
                "path": "steady-3.jpg",
                "datetime": datetime(2026, 3, 12, 18, 20, 0).strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp": datetime(2026, 3, 12, 18, 20, 0).timestamp(),
                "passed": True,
                "score": 32.0,
                "score_left": 31.0,
                "score_right": 33.0,
                "fail_reason": [],
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            report = build_face_report(results, Path(tmpdir))

        self.assertEqual(report["count"], 3)
        self.assertEqual(report["lightest"]["path"], "steady-1.jpg")
        self.assertEqual(report["heaviest"]["path"], "steady-3.jpg")
        self.assertEqual(
            [point["score"] for point in report["trend_views"]["day"]["points"]],
            [30.0, 31.0, 32.0],
        )

    def test_analyze_image_data_falls_back_when_parser_misses_eye_masks(self):
        result = analyze_image_data(
            self.make_test_image(),
            detector=FakeDetector(bbox=(0, 0, 100, 100)),
            parser=FakeParserWithoutEyes(),
            source_path="photo.jpg",
            observed_at=datetime(2026, 3, 11, 12, 7, 0),
            config=AnalysisConfig(min_face_size=80),
        )

        self.assertTrue(result["passed"])
        self.assertGreater(result["score"], 0)

    def test_analyze_image_data_uses_face_crop_for_blur_gate(self):
        image = np.full((1000, 1000, 3), 127, dtype=np.uint8)

        # Background stays flat, but the detected face crop contains clear edges.
        image[460:540, 460:540] = (30, 30, 30)
        image[476:524, 476:524] = (220, 220, 220)
        image[490:510, 476:524] = (20, 20, 20)

        result = analyze_image_data(
            image,
            detector=FakeDetector(bbox=(460, 460, 80, 80)),
            parser=FakeParser(),
            source_path="photo.jpg",
            observed_at=datetime(2026, 3, 11, 12, 10, 0),
            config=AnalysisConfig(
                blur_threshold=100,
                min_face_size=40,
                max_face_center_offset_ratio=1.0,
                min_face_box_aspect_ratio=0.01,
                max_face_box_aspect_ratio=99.0,
                min_mean_brightness=0.0,
                max_mean_brightness=255.0,
                max_dark_pixel_ratio=1.0,
                max_bright_pixel_ratio=1.0,
                min_under_eye_pixels=1,
                max_eye_area_ratio=999,
                max_left_right_score_gap=999,
                max_brightness_l_gap=999,
                max_eye_center_y_ratio=1.0,
                max_eye_width_ratio=999,
            ),
        )

        self.assertTrue(result["passed"])

    def test_analyze_image_data_merges_fallback_skin_when_primary_skin_is_sparse(self):
        result = analyze_image_data(
            self.make_test_image(),
            detector=FakeDetector(bbox=(0, 0, 100, 100)),
            parser=FakeParserWithSparsePrimarySkin(),
            source_path="photo.jpg",
            observed_at=datetime(2026, 3, 11, 12, 12, 0),
            config=AnalysisConfig(min_face_size=80),
        )

        self.assertTrue(result["passed"])

    def test_analyze_image_data_rejects_unstable_left_right_gap(self):
        with patch(
            "src.services.face_analysis_pipeline._analyze_eye_region",
            side_effect=[
                {
                    "score": 10.0,
                    "delta_l": 10.0,
                    "delta_e": 10.0,
                    "under_mask_pixels": 100,
                    "cheek_mask_pixels": 100,
                    "under_l": 20.0,
                    "cheek_l": 30.0,
                    "eye_box": (20, 20, 15, 8),
                },
                {
                    "score": 40.5,
                    "delta_l": 10.0,
                    "delta_e": 10.0,
                    "under_mask_pixels": 100,
                    "cheek_mask_pixels": 100,
                    "under_l": 21.0,
                    "cheek_l": 31.0,
                    "eye_box": (60, 20, 15, 8),
                },
            ],
        ):
            result = analyze_image_data(
                self.make_test_image(),
                detector=FakeDetector(bbox=(0, 0, 100, 100)),
                parser=FakeParser(),
                source_path="photo.jpg",
                observed_at=datetime(2026, 3, 11, 12, 20, 0),
                config=AnalysisConfig(min_face_size=80),
            )

        self.assertFalse(result["passed"])
        self.assertIn("UnstableLeftRightGap", result["fail_reason"])
        self.assertIsNone(result["score"])

    def test_analyze_image_data_rejects_unstable_brightness(self):
        with patch(
            "src.services.face_analysis_pipeline._analyze_eye_region",
            side_effect=[
                {
                    "score": 20.0,
                    "delta_l": 10.0,
                    "delta_e": 10.0,
                    "under_mask_pixels": 100,
                    "cheek_mask_pixels": 100,
                    "under_l": 15.0,
                    "cheek_l": 55.0,
                    "eye_box": (20, 20, 15, 8),
                },
                {
                    "score": 21.0,
                    "delta_l": 10.0,
                    "delta_e": 10.0,
                    "under_mask_pixels": 100,
                    "cheek_mask_pixels": 100,
                    "under_l": 35.0,
                    "cheek_l": 35.0,
                    "eye_box": (60, 20, 15, 8),
                },
            ],
        ):
            result = analyze_image_data(
                self.make_test_image(),
                detector=FakeDetector(bbox=(0, 0, 100, 100)),
                parser=FakeParser(),
                source_path="photo.jpg",
                observed_at=datetime(2026, 3, 11, 12, 21, 0),
                config=AnalysisConfig(min_face_size=80),
            )

        self.assertFalse(result["passed"])
        self.assertIn("UnstableBrightness", result["fail_reason"])

    def test_analyze_image_data_rejects_unstable_pose(self):
        with patch(
            "src.services.face_analysis_pipeline._analyze_eye_region",
            side_effect=[
                {
                    "score": 20.0,
                    "delta_l": 10.0,
                    "delta_e": 10.0,
                    "under_mask_pixels": 100,
                    "cheek_mask_pixels": 100,
                    "under_l": 20.0,
                    "cheek_l": 30.0,
                    "eye_box": (20, 10, 10, 8),
                },
                {
                    "score": 22.0,
                    "delta_l": 10.0,
                    "delta_e": 10.0,
                    "under_mask_pixels": 100,
                    "cheek_mask_pixels": 100,
                    "under_l": 21.0,
                    "cheek_l": 31.0,
                    "eye_box": (60, 40, 30, 8),
                },
            ],
        ):
            result = analyze_image_data(
                self.make_test_image(),
                detector=FakeDetector(bbox=(0, 0, 100, 100)),
                parser=FakeParser(),
                source_path="photo.jpg",
                observed_at=datetime(2026, 3, 11, 12, 22, 0),
                config=AnalysisConfig(min_face_size=80),
            )

        self.assertFalse(result["passed"])
        self.assertIn("UnstablePose", result["fail_reason"])

    def test_analyze_image_data_rejects_unstable_face_box(self):
        image = np.full((200, 200, 3), 120, dtype=np.uint8)

        result = analyze_image_data(
            image,
            detector=FakeDetector(bbox=(0, 0, 60, 60)),
            parser=FakeParser(),
            source_path="photo.jpg",
            observed_at=datetime(2026, 3, 11, 12, 23, 0),
            config=AnalysisConfig(
                blur_threshold=0,
                min_face_size=20,
                min_mean_brightness=0.0,
                max_mean_brightness=255.0,
                max_dark_pixel_ratio=1.0,
                max_bright_pixel_ratio=1.0,
            ),
        )

        self.assertFalse(result["passed"])
        self.assertIn("UnstableFaceBox", result["fail_reason"])

    def test_analyze_image_data_rejects_unstable_eye_area(self):
        with patch(
            "src.services.face_analysis_pipeline._analyze_eye_region",
            side_effect=[
                {
                    "score": 20.0,
                    "delta_l": 10.0,
                    "delta_e": 10.0,
                    "under_mask_pixels": 100,
                    "cheek_mask_pixels": 100,
                    "under_l": 20.0,
                    "cheek_l": 30.0,
                    "eye_box": (20, 20, 10, 8),
                },
                {
                    "score": 21.0,
                    "delta_l": 10.0,
                    "delta_e": 10.0,
                    "under_mask_pixels": 100,
                    "cheek_mask_pixels": 100,
                    "under_l": 21.0,
                    "cheek_l": 31.0,
                    "eye_box": (60, 20, 10, 30),
                },
            ],
        ):
            result = analyze_image_data(
                self.make_test_image(),
                detector=FakeDetector(bbox=(0, 0, 100, 100)),
                parser=FakeParser(),
                source_path="photo.jpg",
                observed_at=datetime(2026, 3, 11, 12, 24, 0),
                config=AnalysisConfig(min_face_size=80),
            )

        self.assertFalse(result["passed"])
        self.assertIn("UnstableEyeArea", result["fail_reason"])

    def test_analyze_image_data_rejects_under_eye_pixels_too_small(self):
        with patch(
            "src.services.face_analysis_pipeline._analyze_eye_region",
            side_effect=[
                {
                    "score": 20.0,
                    "delta_l": 10.0,
                    "delta_e": 10.0,
                    "under_mask_pixels": 10,
                    "cheek_mask_pixels": 100,
                    "under_l": 20.0,
                    "cheek_l": 30.0,
                    "eye_box": (20, 20, 15, 8),
                },
                {
                    "score": 21.0,
                    "delta_l": 10.0,
                    "delta_e": 10.0,
                    "under_mask_pixels": 100,
                    "cheek_mask_pixels": 100,
                    "under_l": 21.0,
                    "cheek_l": 31.0,
                    "eye_box": (60, 20, 15, 8),
                },
            ],
        ):
            result = analyze_image_data(
                self.make_test_image(),
                detector=FakeDetector(bbox=(0, 0, 100, 100)),
                parser=FakeParser(),
                source_path="photo.jpg",
                observed_at=datetime(2026, 3, 11, 12, 25, 0),
                config=AnalysisConfig(min_face_size=80, min_under_eye_pixels=50),
            )

        self.assertFalse(result["passed"])
        self.assertIn("UnderEyePixelsTooSmall", result["fail_reason"])

    def test_analyze_image_data_rejects_extreme_exposure(self):
        image = np.full((100, 100, 3), 250, dtype=np.uint8)

        result = analyze_image_data(
            image,
            detector=FakeDetector(bbox=(0, 0, 100, 100)),
            parser=FakeParser(),
            source_path="photo.jpg",
            observed_at=datetime(2026, 3, 11, 12, 26, 0),
            config=AnalysisConfig(
                blur_threshold=0,
                min_face_size=80,
                max_face_center_offset_ratio=1.0,
                min_face_box_aspect_ratio=0.01,
                max_face_box_aspect_ratio=99.0,
            ),
        )

        self.assertFalse(result["passed"])
        self.assertIn("ExtremeExposure", result["fail_reason"])


class FaceParserFallbackTests(unittest.TestCase):
    def test_infer_fallback_initializes_mesh_when_missing(self):
        parser = FaceParser.__new__(FaceParser)

        with patch.object(FaceParser, "_init_fallback") as init_fallback, patch.object(
            FaceParser,
            "_infer_fallback",
            return_value=np.zeros((512, 512), dtype=np.uint8),
        ):
            result = FaceParser.infer_fallback(parser, np.zeros((512, 512, 3), dtype=np.uint8))

        init_fallback.assert_called_once_with()
        self.assertEqual(result.shape, (512, 512))


if __name__ == "__main__":
    unittest.main()

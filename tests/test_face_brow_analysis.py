"""Synthetic, non-private coverage of the strict shared dark-circle ROI."""

import importlib
import importlib.util

import numpy as np
import pytest


def api():
    name = "src.services.face_brow_analysis"
    assert importlib.util.find_spec(name) is not None, "shared brow-eye analysis is not implemented"
    return importlib.import_module(name)


def face_map():
    parsing = np.ones((160, 200), dtype=np.uint8)
    parsing[35:40, 35:75] = 2
    parsing[35:40, 125:165] = 3
    parsing[50:60, 40:70] = 4
    parsing[50:60, 130:160] = 5
    return parsing


def textured_photo():
    yy, xx = np.indices((160, 200))
    gray = (135 + ((xx + yy) % 2) * 12).astype(np.uint8)
    return np.repeat(gray[:, :, None], 3, axis=2)


def test_gap_controls_skin_band_and_cheek_never_overlaps():
    result = api().build_brow_regions(face_map())
    assert result["status"] == "roi_computed"
    for side in ("left", "right"):
        region = result[side]
        assert region["brow_eye_gap_px"] == 10
        assert region["under_mask"].sum() >= 20
        assert not region["under_mask"][:60].any()
        assert not (region["under_mask"] & region["cheek_mask"]).any()
        assert region["cheek_mask"].sum() >= 20
        assert np.all(face_map()[region["under_mask"]] == 1)


@pytest.mark.parametrize("remove,status", [(4, "eyes_missing"), (2, "brows_missing")])
def test_missing_anchor_never_invents_an_eye(remove, status):
    parsing = face_map()
    parsing[parsing == remove] = 1
    result = api().build_brow_regions(parsing)
    assert result["status"] == status
    assert result.get("left") is None
    assert result.get("right") is None


def test_pooled_components_do_not_require_left_right_class_labels():
    parsing = face_map()
    parsing[parsing == 5] = 4
    parsing[parsing == 3] = 2
    result = api().build_brow_regions(parsing)
    assert result["status"] == "roi_computed"
    assert result["left"]["eye_box"][0] < result["right"]["eye_box"][0]


def test_brow_below_eye_is_rejected():
    parsing = face_map()
    parsing[parsing == 2] = 1
    parsing[70:75, 35:75] = 2
    assert api().build_brow_regions(parsing)["status"] == "brow_eye_gap_missing"


def test_non_skin_and_insufficient_reference_are_rejected():
    parsing = face_map()
    parsing[60:80, :] = 17
    assert api().build_brow_regions(parsing)["status"] == "under_eye_skin_missing"
    parsing = face_map()
    parsing[75:, :] = 0
    assert api().build_brow_regions(parsing)["status"] == "cheek_skin_missing"


def test_passed_output_compatible_with_existing_records():
    result = api().analyze_segmented_face(textured_photo(), face_map())
    assert result["passed"]
    assert result["fail_reason"] == []
    assert 0 <= result["score"] <= 100
    assert result["score"] == (result["score_left"] + result["score_right"]) / 2
    assert result["features"]["brow_eye_gap_px_left"] == 10
    assert 0 <= result["quality"]["lighting_confidence"] <= 1
    assert result["regions"]["status"] == "roi_computed"


def test_darkened_under_eye_has_larger_relative_score():
    module = api()
    image = textured_photo()
    regions = module.build_brow_regions(face_map())
    baseline = module.analyze_segmented_face(image, face_map())
    darkened = image.copy()
    mask = regions["left"]["under_mask"] | regions["right"]["under_mask"]
    darkened[mask] = np.maximum(darkened[mask].astype(int) - 35, 0).astype(np.uint8)
    result = module.analyze_segmented_face(darkened, face_map())
    assert result["passed"]
    assert result["score"] > baseline["score"]


@pytest.mark.parametrize("value", [0, 255])
def test_bad_exposure_produces_no_score(value):
    result = api().analyze_segmented_face(np.full((160, 200, 3), value, np.uint8), face_map())
    assert not result["passed"]
    assert result["score"] is None
    assert "ExtremeExposure" in result["fail_reason"]


def test_blurred_photo_produces_no_score():
    result = api().analyze_segmented_face(np.full((160, 200, 3), 140, np.uint8), face_map())
    assert not result["passed"]
    assert result["score"] is None
    assert any(reason.startswith("Blurry") for reason in result["fail_reason"])


def test_invalid_input_and_unstable_pose_do_not_score():
    module = api()
    assert module.analyze_segmented_face(None, face_map())["fail_reason"] == ["ReadError"]
    assert module.build_brow_regions(np.zeros((2, 2, 3)))["status"] == "invalid_parsing_map"
    parsing = face_map()
    parsing[parsing == 3] = 1
    parsing[parsing == 5] = 1
    parsing[75:80, 125:165] = 3
    parsing[90:100, 130:160] = 5
    result = module.analyze_segmented_face(textured_photo(), parsing)
    assert not result["passed"]
    assert "UnstablePose" in result["fail_reason"]


def test_one_sided_reference_lighting_is_rejected():
    module = api()
    image = textured_photo()
    image[:, 100:] = np.clip(image[:, 100:].astype(int) + 35, 0, 255).astype(np.uint8)
    result = module.analyze_segmented_face(image, face_map())
    assert not result["passed"]
    assert result["score"] is None
    assert "UnstableLighting" in result["fail_reason"]


def test_dark_background_does_not_count_as_dark_skin_exposure():
    module = api()
    parsing = face_map()
    parsing[:20] = 0
    parsing[110:] = 0
    parsing[:, :20] = 0
    parsing[:, 180:] = 0
    image = textured_photo()
    image[parsing == 0] = 0
    result = module.analyze_segmented_face(image, parsing)
    assert "ExtremeExposure" not in result["fail_reason"]


def test_shape_mismatch_does_not_resize_labels_silently():
    result = api().analyze_segmented_face(np.zeros((40, 40, 3), np.uint8), face_map())
    assert not result["passed"]
    assert result["fail_reason"] == ["ParsingSizeMismatch"]


def test_cheek_outside_photo_is_not_replaced_with_fabricated_skin():
    assert api().build_brow_regions(face_map()[:74])["status"] == "cheek_skin_missing"


def test_small_spurious_components_are_ignored():
    parsing = face_map()
    parsing[5, 5] = 4
    parsing[5, 195] = 2
    result = api().build_brow_regions(parsing)
    assert result["status"] == "roi_computed"
    assert result["left"]["eye_box"] == (40, 50, 30, 10)

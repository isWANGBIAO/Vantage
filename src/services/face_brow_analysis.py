"""Model-independent, strict brow/eye sampling and relative appearance scoring.

Inputs use the standard 19-class face parsing labels. Left/right mean image
left/right, not anatomical sides. No face/eye mask is ever synthesized.
This is an appearance measurement, not a medical severity assessment.
Only NumPy/OpenCV are needed in the user-selected external model environment.
"""

from dataclasses import dataclass

from src.core.cpu_runtime_policy import configure_cpu_runtime

configure_cpu_runtime()

import cv2
import numpy as np

from src.utils.face_score import normalize_dark_circle_score


ALGORITHM_VERSION = "brow-eye-relative-v1"


@dataclass
class BrowAnalysisConfig:
    blur_threshold: float = 50.0
    min_mask_pixels: int = 12
    min_under_eye_pixels: int = 60
    min_mean_brightness: float = 45.0
    max_mean_brightness: float = 210.0
    max_dark_pixel_ratio: float = 0.55
    max_bright_pixel_ratio: float = 0.40
    max_eye_area_ratio: float = 2.5
    max_eye_width_ratio: float = 1.8
    max_eye_center_y_ratio: float = 0.1
    max_left_right_score_gap: float = 20.0
    max_brightness_l_gap: float = 18.0
    max_skin_l_std_ratio: float = 0.28
    illumination_blur_sigma: float = 21.0
    skin_tone_target_a: float = 128.0
    skin_tone_target_b: float = 128.0
    score_scale: float = 60.0
    score_relative_l_weight: float = 0.5
    score_shadow_contrast_weight: float = 0.35
    score_normalized_delta_e_weight: float = 0.15


def _components(mask):
    count, labels, stats, centers = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    indices = sorted(
        (i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] >= 8),
        key=lambda i: stats[i, cv2.CC_STAT_AREA],
        reverse=True,
    )[:2]
    return sorted(
        ((labels == i, centers[i]) for i in indices), key=lambda item: item[1][0]
    )


def build_brow_regions(parsing_map):
    """Return strict skin sampling masks; failed results contain no regions."""
    failed = lambda status: {"status": status, "left": None, "right": None}
    if not isinstance(parsing_map, np.ndarray) or parsing_map.ndim != 2 or not parsing_map.size:
        return failed("invalid_parsing_map")
    eyes = _components(np.isin(parsing_map, [4, 5]))
    brows = _components(np.isin(parsing_map, [2, 3]))
    if len(eyes) != 2:
        return failed("eyes_missing")
    if len(brows) != 2:
        return failed("brows_missing")
    skin = parsing_map == 1
    height, width = parsing_map.shape
    yy = np.arange(height)[:, None]
    regions = []
    for (eye, _), (brow, _) in zip(eyes, brows):
        xs = np.flatnonzero(eye.any(axis=0))
        brow_xs = np.flatnonzero(brow.any(axis=0))
        gaps = []
        for x in np.intersect1d(xs, brow_xs):
            top = np.flatnonzero(eye[:, x])[0]
            bottom = np.flatnonzero(brow[:, x])[-1]
            if top > bottom:
                gaps.append(top - bottom - 1)
        if not gaps:
            return failed("brow_eye_gap_missing")
        gap = max(1, int(round(float(np.median(gaps)))))
        distance = cv2.distanceTransform((~eye).astype(np.uint8), cv2.DIST_L2, 5)
        lower = np.interp(
            np.arange(width), xs, [np.flatnonzero(eye[:, x])[-1] for x in xs]
        )[None, :]
        under = (distance <= gap) & ~eye & skin & (yy > lower)
        if int(under.sum()) < 20:
            return failed("under_eye_skin_missing")
        coords = cv2.findNonZero(eye.astype(np.uint8))
        box = tuple(int(v) for v in cv2.boundingRect(coords))
        regions.append({"under_mask": under, "eye_mask": eye, "brow_mask": brow,
                        "eye_box": box, "brow_eye_gap_px": gap})

    # Reference rectangles begin below the entire expanded band, not inside it.
    excluded = regions[0]["under_mask"] | regions[1]["under_mask"]
    for region in regions:
        x, _, eye_width, _ = region["eye_box"]
        gap = region["brow_eye_gap_px"]
        bottom = int(np.flatnonzero(region["under_mask"].any(axis=1))[-1])
        cheek_y = bottom + 1 + max(2, gap // 2)
        cheek_x = x + int(eye_width * 0.1)
        cheek_width = max(2, int(eye_width * 0.8))
        cheek = np.zeros_like(skin)
        cheek[cheek_y:min(height, cheek_y + max(2, gap)),
              cheek_x:min(width, cheek_x + cheek_width)] = True
        cheek &= skin & ~excluded
        if int(cheek.sum()) < 20:
            return failed("cheek_skin_missing")
        region["cheek_mask"] = cheek
    return {"status": "roi_computed", "left": regions[0], "right": regions[1]}


def _normalized_lab(image, skin, config):
    # Preserve the existing Vantage Retinex and chroma centering convention.
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32) + 1.0
    sigma = max(1.0, float(config.illumination_blur_sigma))
    background = cv2.GaussianBlur(gray, (0, 0), sigmaX=sigma, sigmaY=sigma)
    retinex = np.log(gray) - np.log(background + 1e-6)
    lab[:, :, 0] = cv2.normalize(retinex, None, 0, 255, cv2.NORM_MINMAX)
    skin_lab = lab[skin]
    for channel, target in ((1, config.skin_tone_target_a), (2, config.skin_tone_target_b)):
        lab[:, :, channel] = np.clip(
            lab[:, :, channel] + float(target) - float(np.median(skin_lab[:, channel])), 0, 255
        )
    return lab, {"face_l_reference": 255.0,
                 "skin_l_std_ratio": float(np.std(lab[skin, 0])) / 255.0}


def _metrics(region, lab, config):
    under = lab[region["under_mask"]]
    cheek = lab[region["cheek_mask"]]
    under_med, cheek_med = np.median(under, axis=0), np.median(cheek, axis=0)
    delta_l = max(0.0, float(cheek_med[0] - under_med[0]))
    delta_e = float(np.linalg.norm(cheek_med - under_med))
    contrast = lambda values: float(np.percentile(values, 90) - np.percentile(values, 10))
    relative = delta_l / 255.0
    shadow = max(0.0, contrast(under[:, 0]) - contrast(cheek[:, 0])) / 255.0
    normalized_delta = delta_e / 255.0
    raw = config.score_scale * (config.score_relative_l_weight * relative
                               + config.score_shadow_contrast_weight * shadow
                               + config.score_normalized_delta_e_weight * normalized_delta)
    return {"score": normalize_dark_circle_score(raw), "raw_score": raw,
            "delta_l": delta_l, "delta_e": delta_e, "relative_luminance": relative,
            "shadow_contrast": shadow, "normalized_delta_e": normalized_delta,
            "under_l": float(under_med[0]), "cheek_l": float(cheek_med[0])}


def analyze_segmented_face(image_bgr, parsing_map, config=None):
    """Score an already-cropped segmented face, or return explicit rejection."""
    config = config or BrowAnalysisConfig()
    result = {"passed": False, "fail_reason": [], "score": None,
              "score_left": None, "score_right": None, "delta_e_left": None,
              "delta_e_right": None, "delta_l_left": None, "delta_l_right": None,
              "features": {}, "quality": {"lighting_confidence": 0.0}, "regions": None}
    if (not isinstance(image_bgr, np.ndarray) or image_bgr.ndim != 3
            or image_bgr.shape[2] != 3 or not image_bgr.size):
        result["fail_reason"] = ["ReadError"]
        return result
    regions = build_brow_regions(parsing_map)
    result["regions"] = regions
    if regions["status"] != "roi_computed":
        result["fail_reason"] = [regions["status"]]
        return result
    if image_bgr.shape[:2] != parsing_map.shape:
        result["fail_reason"] = ["ParsingSizeMismatch"]
        return result
    skin = parsing_map == 1
    if int(skin.sum()) < config.min_mask_pixels * 10:
        result["fail_reason"] = ["FaceMaskTooSmall"]
        return result
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    values = gray[skin]
    if (values.mean() < config.min_mean_brightness or values.mean() > config.max_mean_brightness
            or np.mean(values <= 30) > config.max_dark_pixel_ratio
            or np.mean(values >= 225) > config.max_bright_pixel_ratio):
        result["fail_reason"].append("ExtremeExposure")
    variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if variance < config.blur_threshold:
        result["fail_reason"].append(f"Blurry({int(variance)})")
    left, right = regions["left"], regions["right"]
    for region in (left, right):
        if region["under_mask"].sum() < config.min_under_eye_pixels:
            result["fail_reason"].append("UnderEyePixelsTooSmall")
    lx, ly, lw, lh = left["eye_box"]
    rx, ry, rw, rh = right["eye_box"]
    if max(lw * lh, rw * rh) / max(1, min(lw * lh, rw * rh)) > config.max_eye_area_ratio:
        result["fail_reason"].append("UnstableEyeArea")
    if (abs(ly + lh / 2 - ry - rh / 2) / image_bgr.shape[0] > config.max_eye_center_y_ratio
            or max(lw, rw) / max(1, min(lw, rw)) > config.max_eye_width_ratio):
        result["fail_reason"].append("UnstablePose")
    if result["fail_reason"]:
        result["fail_reason"] = list(dict.fromkeys(result["fail_reason"]))
        return result
    lab, stats = _normalized_lab(image_bgr, skin, config)
    lm, rm = _metrics(left, lab, config), _metrics(right, lab, config)
    if abs(lm["raw_score"] - rm["raw_score"]) > config.max_left_right_score_gap:
        result["fail_reason"].append("UnstableLeftRightGap")
    if abs(lm["relative_luminance"] - rm["relative_luminance"]) * 100 > config.max_brightness_l_gap:
        result["fail_reason"].append("UnstableBrightness")
    # Large raw reference asymmetry is evidence of one-sided lighting, even if
    # Retinex normalization would otherwise conceal it.
    raw_lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    cheek_gap = abs(float(np.median(raw_lab[left["cheek_mask"], 0]))
                    - float(np.median(raw_lab[right["cheek_mask"], 0])))
    if cheek_gap > config.max_brightness_l_gap:
        result["fail_reason"].append("UnstableLighting")
    gap = max(abs(lm["under_l"] - rm["under_l"]), abs(lm["cheek_l"] - rm["cheek_l"])) / 255
    excess = max(0.0, stats["skin_l_std_ratio"] - config.max_skin_l_std_ratio)
    confidence = float(np.clip(1 - min(1, gap * 2 + excess * 2.5), 0, 1))
    result["quality"] = {"lighting_confidence": confidence,
                         "blur_variance": variance, "reference_brightness_gap": cheek_gap}
    if result["fail_reason"]:
        return result
    for side, metrics in (("left", lm), ("right", rm)):
        for key in ("score", "delta_e", "delta_l"):
            result[f"{key}_{side}"] = metrics[key]
        for key in ("relative_luminance", "shadow_contrast", "normalized_delta_e"):
            result["features"][f"{key}_{side}"] = metrics[key]
        result["features"][f"brow_eye_gap_px_{side}"] = regions[side]["brow_eye_gap_px"]
    result["score"] = (lm["score"] + rm["score"]) / 2
    result["passed"] = True
    return result

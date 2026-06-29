import os
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from src.utils.face_score import normalize_dark_circle_score

TREND_VIEW_LABELS = {
    "day": "最近24小时",
    "week": "最近7天",
    "month": "最近30天",
    "all": "全部历史",
}


CLASS_IDX = {
    "background": 0,
    "skin": 1,
    "l_brow": 2,
    "r_brow": 3,
    "l_eye": 4,
    "r_eye": 5,
    "eye_g": 6,
    "l_ear": 7,
    "r_ear": 8,
    "ear_r": 9,
    "nose": 10,
    "mouth": 11,
    "u_lip": 12,
    "l_lip": 13,
    "neck": 14,
    "neck_l": 15,
    "cloth": 16,
    "hair": 17,
    "hat": 18,
}


@dataclass
class AnalysisConfig:
    min_detection_confidence: float = 0.5
    face_padding_ratio: float = 0.35
    blur_threshold: float = 50.0
    min_face_size: int = 120
    min_mask_pixels: int = 12
    under_band_ratio: float = 0.45
    cheek_offset_ratio: float = 0.75
    score_delta_e_weight: float = 0.6
    score_delta_l_weight: float = 0.4
    score_relative_l_weight: float = 0.5
    score_shadow_contrast_weight: float = 0.35
    score_normalized_delta_e_weight: float = 0.15
    score_scale: float = 60.0
    max_face_center_offset_ratio: float = 0.32
    min_face_box_aspect_ratio: float = 0.75
    max_face_box_aspect_ratio: float = 1.35
    min_mean_brightness: float = 45.0
    max_mean_brightness: float = 210.0
    max_dark_pixel_ratio: float = 0.55
    max_bright_pixel_ratio: float = 0.40
    min_under_eye_pixels: int = 60
    max_eye_area_ratio: float = 2.5
    max_left_right_score_gap: float = 20.0
    max_brightness_l_gap: float = 18.0
    max_eye_center_y_ratio: float = 0.1
    max_eye_width_ratio: float = 1.8
    illumination_clahe_clip_limit: float = 2.0
    illumination_clahe_grid_size: int = 8
    illumination_blur_sigma: float = 21.0
    skin_tone_target_a: float = 128.0
    skin_tone_target_b: float = 128.0
    max_skin_l_std_ratio: float = 0.28


class MediaPipeFaceDetector:
    def __init__(self, min_detection_confidence: float = 0.5):
        self.min_detection_confidence = float(min_detection_confidence)
        cascade_path = self._resolve_cascade_path()
        self._cascade = cv2.CascadeClassifier(str(cascade_path))
        if self._cascade.empty():
            raise RuntimeError(f"Failed to load OpenCV face cascade: {cascade_path}")

    @staticmethod
    def _resolve_cascade_path():
        cascade_name = "haarcascade_frontalface_default.xml"
        candidate_paths = []

        configured_path = os.environ.get("VANTAGE_FACE_CASCADE_PATH")
        if configured_path:
            candidate_paths.append(Path(configured_path))

        meipass_root = getattr(sys, "_MEIPASS", None)
        if meipass_root:
            candidate_paths.append(Path(meipass_root) / "opencv-data" / cascade_name)

        executable_parent = Path(sys.executable).resolve().parent
        candidate_paths.extend(
            [
                executable_parent / "_internal" / "opencv-data" / cascade_name,
                executable_parent / "opencv-data" / cascade_name,
                Path(cv2.data.haarcascades) / cascade_name,
            ]
        )

        for candidate_path in candidate_paths:
            if candidate_path.exists():
                return candidate_path.resolve()

        raise FileNotFoundError(
            "OpenCV face cascade not found in packaged runtime or local OpenCV data paths."
        )

    def detect(self, image_bgr):
        if image_bgr is None or image_bgr.size == 0:
            return None

        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        h, w = image_bgr.shape[:2]
        min_side = max(32, int(min(h, w) * 0.2))
        min_neighbors = max(3, int(round(3 + (self.min_detection_confidence * 4))))
        detections = self._cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=min_neighbors,
            minSize=(min_side, min_side),
        )
        if len(detections) == 0:
            return None

        best_bbox = max(detections, key=lambda bbox: int(bbox[2]) * int(bbox[3]))
        return tuple(int(value) for value in best_bbox)


class FaceParser:
    def __init__(self, model_path, provider="CPUExecutionProvider"):
        self.use_fallback = False
        self.model_path = model_path

        if not os.path.exists(model_path):
            self.use_fallback = True
            self._init_fallback()
            return

        import onnxruntime as ort

        try:
            sess_options = ort.SessionOptions()
            sess_options.log_severity_level = 3
            available = ort.get_available_providers()
            if provider == "CUDAExecutionProvider" and provider not in available:
                provider = "CPUExecutionProvider"
            self.session = ort.InferenceSession(model_path, sess_options, providers=[provider])
            self.input_name = self.session.get_inputs()[0].name
        except Exception:
            self.use_fallback = True
            self._init_fallback()

    def _init_fallback(self):
        self._fallback_ready = True

    def preprocess(self, img_bgr):
        resized = cv2.resize(img_bgr, (512, 512), interpolation=cv2.INTER_LINEAR)
        if self.use_fallback:
            return None, resized

        img_rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        img_norm = (img_rgb.astype(np.float32) - 127.5) / 127.5
        blob = np.expand_dims(img_norm.transpose(2, 0, 1), axis=0)
        return blob, resized

    def infer(self, img_bgr):
        blob, resized = self.preprocess(img_bgr)
        if self.use_fallback:
            return self._infer_fallback(resized), resized

        outputs = self.session.run(None, {self.input_name: blob})
        parsing_map = outputs[0][0].argmax(0).astype(np.uint8)
        return parsing_map, resized

    def infer_fallback(self, img_bgr):
        if not getattr(self, "_fallback_ready", False):
            self._init_fallback()
        if img_bgr.shape[:2] != (512, 512):
            _, resized = self.preprocess(img_bgr)
        else:
            resized = img_bgr
        return self._infer_fallback(resized)

    def _infer_fallback(self, resized):
        h, w = resized.shape[:2]
        parsing_map = np.zeros((h, w), dtype=np.uint8)
        face_center = (int(w * 0.5), int(h * 0.52))
        face_axes = (max(1, int(w * 0.34)), max(1, int(h * 0.44)))
        cv2.ellipse(parsing_map, face_center, face_axes, 0, 0, 360, CLASS_IDX["skin"], -1)

        eye_axes = (max(1, int(w * 0.085)), max(1, int(h * 0.04)))
        left_eye_center = (int(w * 0.37), int(h * 0.41))
        right_eye_center = (int(w * 0.63), int(h * 0.41))
        cv2.ellipse(parsing_map, left_eye_center, eye_axes, 0, 0, 360, CLASS_IDX["l_eye"], -1)
        cv2.ellipse(parsing_map, right_eye_center, eye_axes, 0, 0, 360, CLASS_IDX["r_eye"], -1)
        return parsing_map


def discover_photo_search_paths():
    onedrive_path = os.environ.get("OneDrive", os.path.expanduser("~\\OneDrive"))
    user_home = os.path.expanduser("~")
    configured_roots = [
        root.strip()
        for root in os.environ.get("VANTAGE_PHOTO_ROOTS", "").split(os.pathsep)
        if root.strip()
    ]
    potential_roots = [
        *configured_roots,
        onedrive_path,
        os.path.join(user_home, "OneDrive"),
        user_home,
    ]
    subdirs = [
        os.path.join("Pictures", "Camera Roll"),
        os.path.join("Pictures", "Saved Pictures"),
        os.path.join("Pictures", "本机照片"),
        os.path.join("图片", "本机照片"),
        "本机照片",
    ]

    paths = []
    for root in potential_roots:
        if root and os.path.exists(root):
            for sub in subdirs:
                candidate = os.path.join(root, sub)
                if os.path.exists(candidate):
                    paths.append(os.path.abspath(candidate))
    return sorted(set(paths))


def scan_photos(search_paths, day=None):
    photo_files = []
    day_prefix = f"photo_{day}_" if day else "photo_"
    for search_path in search_paths:
        for root, _, files in os.walk(search_path):
            for file in files:
                if not (file.startswith(day_prefix) and file.endswith(".jpg")):
                    continue
                try:
                    ts_str = file.replace("photo_", "").replace(".jpg", "")
                    observed_at = datetime.strptime(ts_str[:15], "%Y%m%d_%H%M%S")
                    photo_files.append(
                        {
                            "path": os.path.join(root, file),
                            "date": observed_at,
                            "timestamp": observed_at.timestamp(),
                        }
                    )
                except ValueError:
                    continue
    photo_files.sort(key=lambda item: item["timestamp"])
    return photo_files


def detect_face_crop(image_bgr, detector, config: AnalysisConfig):
    bbox = detector.detect(image_bgr)
    if not bbox:
        return None, None, None

    h, w = image_bgr.shape[:2]
    x, y, bw, bh = bbox
    if bw < config.min_face_size or bh < config.min_face_size:
        return None, "FaceTooSmall", bbox

    pad_x = int(bw * config.face_padding_ratio)
    pad_y = int(bh * config.face_padding_ratio)
    x0 = max(0, x - pad_x)
    y0 = max(0, y - pad_y)
    x1 = min(w, x + bw + pad_x)
    y1 = min(h, y + bh + pad_y)
    crop = image_bgr[y0:y1, x0:x1]
    if crop.size == 0:
        return None, "FaceCropEmpty", bbox
    return crop, None, bbox


def _mask_box(mask):
    coords = cv2.findNonZero(mask.astype(np.uint8))
    if coords is None:
        return None
    return cv2.boundingRect(coords)


def _normalize_face_lab(resized_img, skin_mask, config: AnalysisConfig):
    lab = cv2.cvtColor(resized_img, cv2.COLOR_BGR2LAB).astype(np.float32)
    gray = cv2.cvtColor(resized_img, cv2.COLOR_BGR2GRAY).astype(np.float32) + 1.0
    background = cv2.GaussianBlur(
        gray,
        (0, 0),
        sigmaX=max(1.0, float(config.illumination_blur_sigma)),
        sigmaY=max(1.0, float(config.illumination_blur_sigma)),
    )
    retinex_l = np.log(gray) - np.log(background + 1e-6)
    normalized_l = cv2.normalize(retinex_l, None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX)
    lab[:, :, 0] = normalized_l

    skin_lab = lab[skin_mask == 1]
    if skin_lab.size:
        a_shift = float(config.skin_tone_target_a) - float(np.median(skin_lab[:, 1]))
        b_shift = float(config.skin_tone_target_b) - float(np.median(skin_lab[:, 2]))
        lab[:, :, 1] = np.clip(lab[:, :, 1] + a_shift, 0, 255)
        lab[:, :, 2] = np.clip(lab[:, :, 2] + b_shift, 0, 255)
        skin_lab = lab[skin_mask == 1]

    if skin_lab.size:
        face_l_reference = 255.0
        skin_l_std_ratio = float(np.std(skin_lab[:, 0])) / face_l_reference
    else:
        face_l_reference = 255.0
        skin_l_std_ratio = 0.0

    return lab, {
        "face_l_reference": face_l_reference,
        "skin_l_std_ratio": skin_l_std_ratio,
    }


def _shadow_contrast(values):
    if values.size == 0:
        return 0.0
    return float(np.percentile(values, 90) - np.percentile(values, 10))


def _analyze_eye_region(parsing_map, normalized_lab, eye_class_idx, skin_mask, face_stats, config: AnalysisConfig):
    eye_mask = (parsing_map == eye_class_idx).astype(np.uint8)
    box = _mask_box(eye_mask)
    if box is None:
        return None

    ex, ey, ew, eh = box
    band_h = max(2, int(eh * config.under_band_ratio))

    under_mask = np.zeros_like(parsing_map, dtype=np.uint8)
    cv2.rectangle(under_mask, (ex, ey + eh), (ex + ew, ey + eh + band_h), 1, -1)
    under_mask = cv2.bitwise_and(under_mask, skin_mask)

    cheek_offset = max(1, int(eh * config.cheek_offset_ratio))
    cheek_h = max(2, int(eh * 0.6))
    cheek_w = max(2, int(ew * 0.8))
    cheek_x = ex + int(ew * 0.1)
    cheek_y = ey + eh + band_h + cheek_offset

    cheek_mask = np.zeros_like(parsing_map, dtype=np.uint8)
    cv2.rectangle(cheek_mask, (cheek_x, cheek_y), (cheek_x + cheek_w, cheek_y + cheek_h), 1, -1)
    cheek_mask = cv2.bitwise_and(cheek_mask, skin_mask)

    if cv2.countNonZero(under_mask) < config.min_mask_pixels:
        return None
    if cv2.countNonZero(cheek_mask) < config.min_mask_pixels:
        return None

    under_pixels = normalized_lab[under_mask == 1]
    cheek_pixels = normalized_lab[cheek_mask == 1]
    under_med = np.median(under_pixels, axis=0)
    cheek_med = np.median(cheek_pixels, axis=0)

    delta_l = max(0.0, float(cheek_med[0] - under_med[0]))
    delta_e = float(np.linalg.norm(cheek_med - under_med))
    face_l_reference = max(1.0, float(face_stats["face_l_reference"]))
    relative_luminance = delta_l / face_l_reference
    shadow_contrast = max(
        0.0,
        _shadow_contrast(under_pixels[:, 0]) - _shadow_contrast(cheek_pixels[:, 0]),
    ) / face_l_reference
    normalized_delta_e = delta_e / face_l_reference
    raw_score = config.score_scale * (
        (config.score_relative_l_weight * relative_luminance)
        + (config.score_shadow_contrast_weight * shadow_contrast)
        + (config.score_normalized_delta_e_weight * normalized_delta_e)
    )

    return {
        "raw_score": raw_score,
        "score": normalize_dark_circle_score(raw_score),
        "delta_l": delta_l,
        "delta_e": delta_e,
        "relative_luminance": relative_luminance,
        "shadow_contrast": shadow_contrast,
        "normalized_delta_e": normalized_delta_e,
        "under_mask_pixels": int(cv2.countNonZero(under_mask)),
        "cheek_mask_pixels": int(cv2.countNonZero(cheek_mask)),
        "under_l": float(under_med[0]),
        "cheek_l": float(cheek_med[0]),
        "eye_box": (ex, ey, ew, eh),
    }


def _compute_lighting_confidence(left_metrics, right_metrics, face_stats, config: AnalysisConfig):
    face_l_reference = max(1.0, float(face_stats.get("face_l_reference", 128.0)))
    brightness_gap_ratio = max(
        abs(left_metrics["under_l"] - right_metrics["under_l"]),
        abs(left_metrics["cheek_l"] - right_metrics["cheek_l"]),
    ) / face_l_reference
    skin_l_std_ratio = max(0.0, float(face_stats.get("skin_l_std_ratio", 0.0)))
    excess_skin_variance = max(0.0, skin_l_std_ratio - float(config.max_skin_l_std_ratio))
    confidence = 1.0 - min(1.0, (brightness_gap_ratio * 2.0) + (excess_skin_variance * 2.5))
    return float(np.clip(confidence, 0.0, 1.0))


def _face_box_fail_reasons(image_bgr, bbox, config: AnalysisConfig):
    if not bbox:
        return []

    h, w = image_bgr.shape[:2]
    x, y, bw, bh = bbox
    cx = x + (bw / 2.0)
    cy = y + (bh / 2.0)
    center_offset_ratio = max(
        abs(cx - (w / 2.0)) / max(1.0, float(w)),
        abs(cy - (h / 2.0)) / max(1.0, float(h)),
    )
    aspect_ratio = bw / max(1.0, float(bh))

    if (
        center_offset_ratio > config.max_face_center_offset_ratio
        or aspect_ratio < config.min_face_box_aspect_ratio
        or aspect_ratio > config.max_face_box_aspect_ratio
    ):
        return ["UnstableFaceBox"]
    return []


def _exposure_fail_reasons(crop_gray, config: AnalysisConfig):
    mean_brightness = float(crop_gray.mean())
    dark_pixel_ratio = float(np.mean(crop_gray <= 30))
    bright_pixel_ratio = float(np.mean(crop_gray >= 225))

    if (
        mean_brightness < config.min_mean_brightness
        or mean_brightness > config.max_mean_brightness
        or dark_pixel_ratio > config.max_dark_pixel_ratio
        or bright_pixel_ratio > config.max_bright_pixel_ratio
    ):
        return ["ExtremeExposure"]
    return []


def _stability_fail_reasons(left_metrics, right_metrics, resized_img, config: AnalysisConfig):
    fail_reasons = []
    left_raw_score = float(left_metrics.get("raw_score", left_metrics.get("score", 0.0)))
    right_raw_score = float(right_metrics.get("raw_score", right_metrics.get("score", 0.0)))

    if min(left_metrics["under_mask_pixels"], right_metrics["under_mask_pixels"]) < config.min_under_eye_pixels:
        fail_reasons.append("UnderEyePixelsTooSmall")

    if abs(left_raw_score - right_raw_score) > config.max_left_right_score_gap:
        fail_reasons.append("UnstableLeftRightGap")

    if "relative_luminance" in left_metrics and "relative_luminance" in right_metrics:
        brightness_gap = abs(left_metrics["relative_luminance"] - right_metrics["relative_luminance"]) * 100.0
    else:
        brightness_gap = max(
            abs(left_metrics["under_l"] - right_metrics["under_l"]),
            abs(left_metrics["cheek_l"] - right_metrics["cheek_l"]),
        )
    if brightness_gap > config.max_brightness_l_gap:
        fail_reasons.append("UnstableBrightness")

    h, _ = resized_img.shape[:2]
    lx, ly, lw, lh = left_metrics["eye_box"]
    rx, ry, rw, rh = right_metrics["eye_box"]
    left_center_y = ly + (lh / 2.0)
    right_center_y = ry + (rh / 2.0)
    eye_center_y_ratio = abs(left_center_y - right_center_y) / max(1.0, float(h))
    eye_width_ratio = max(lw, rw) / max(1.0, float(min(lw, rw)))
    eye_area_ratio = max(lw * lh, rw * rh) / max(1.0, float(min(lw * lh, rw * rh)))

    if eye_area_ratio > config.max_eye_area_ratio:
        fail_reasons.append("UnstableEyeArea")

    if eye_center_y_ratio > config.max_eye_center_y_ratio or eye_width_ratio > config.max_eye_width_ratio:
        fail_reasons.append("UnstablePose")

    return fail_reasons


def analyze_image_data(image_bgr, detector, parser, source_path="", observed_at=None, config=None):
    config = config or AnalysisConfig()
    observed_at = observed_at or datetime.now()

    result = {
        "path": source_path,
        "datetime": observed_at.strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp": observed_at.timestamp(),
        "passed": False,
        "fail_reason": [],
        "score": None,
        "score_left": None,
        "score_right": None,
        "delta_e_left": None,
        "delta_e_right": None,
        "delta_l_left": None,
        "delta_l_right": None,
        "features": {},
        "quality": {
            "lighting_confidence": 0.0,
        },
    }

    if image_bgr is None or image_bgr.size == 0:
        result["fail_reason"].append("ReadError")
        return result

    crop, crop_error, bbox = detect_face_crop(image_bgr, detector, config)
    if crop is None:
        result["fail_reason"].append("NoFace" if crop_error is None else crop_error)
        return result

    result["fail_reason"].extend(_face_box_fail_reasons(image_bgr, bbox, config))
    if result["fail_reason"]:
        return result

    crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    variance = cv2.Laplacian(crop_gray, cv2.CV_64F).var()
    if variance < config.blur_threshold:
        result["fail_reason"].append(f"Blurry({int(variance)})")
        return result

    result["fail_reason"].extend(_exposure_fail_reasons(crop_gray, config))
    if result["fail_reason"]:
        return result

    parsing_map, resized_img = parser.infer(crop)
    left_eye_pixels = int(np.count_nonzero(parsing_map == CLASS_IDX["l_eye"]))
    right_eye_pixels = int(np.count_nonzero(parsing_map == CLASS_IDX["r_eye"]))
    if (left_eye_pixels == 0 or right_eye_pixels == 0) and hasattr(parser, "infer_fallback"):
        fallback_map = parser.infer_fallback(resized_img)
        if left_eye_pixels == 0:
            parsing_map[fallback_map == CLASS_IDX["l_eye"]] = CLASS_IDX["l_eye"]
        if right_eye_pixels == 0:
            parsing_map[fallback_map == CLASS_IDX["r_eye"]] = CLASS_IDX["r_eye"]
        parsing_map[fallback_map == CLASS_IDX["skin"]] = CLASS_IDX["skin"]

    skin_mask = (parsing_map == CLASS_IDX["skin"]).astype(np.uint8)
    if cv2.countNonZero(skin_mask) < config.min_mask_pixels * 10:
        result["fail_reason"].append("FaceMaskTooSmall")
        return result

    normalized_lab, face_stats = _normalize_face_lab(resized_img, skin_mask, config)
    left_metrics = _analyze_eye_region(
        parsing_map,
        normalized_lab,
        CLASS_IDX["l_eye"],
        skin_mask,
        face_stats,
        config,
    )
    right_metrics = _analyze_eye_region(
        parsing_map,
        normalized_lab,
        CLASS_IDX["r_eye"],
        skin_mask,
        face_stats,
        config,
    )

    if left_metrics is None:
        result["fail_reason"].append("LeftEyeROIInvalid")
    if right_metrics is None:
        result["fail_reason"].append("RightEyeROIInvalid")
    if result["fail_reason"]:
        return result

    result["fail_reason"].extend(_stability_fail_reasons(left_metrics, right_metrics, resized_img, config))
    if result["fail_reason"]:
        return result

    result["score_left"] = left_metrics["score"]
    result["score_right"] = right_metrics["score"]
    result["score"] = (left_metrics["score"] + right_metrics["score"]) / 2.0
    result["delta_e_left"] = left_metrics["delta_e"]
    result["delta_e_right"] = right_metrics["delta_e"]
    result["delta_l_left"] = left_metrics["delta_l"]
    result["delta_l_right"] = right_metrics["delta_l"]
    result["features"] = {
        "relative_luminance_left": left_metrics.get("relative_luminance"),
        "relative_luminance_right": right_metrics.get("relative_luminance"),
        "shadow_contrast_left": left_metrics.get("shadow_contrast"),
        "shadow_contrast_right": right_metrics.get("shadow_contrast"),
        "normalized_delta_e_left": left_metrics.get("normalized_delta_e"),
        "normalized_delta_e_right": right_metrics.get("normalized_delta_e"),
    }
    result["quality"] = {
        "lighting_confidence": _compute_lighting_confidence(left_metrics, right_metrics, face_stats, config),
    }
    result["passed"] = True
    return result


def analyze_photo_file(photo_path, detector, parser, config=None):
    basename = os.path.basename(photo_path)
    ts_str = basename.replace("photo_", "").replace(".jpg", "")
    observed_at = datetime.strptime(ts_str[:15], "%Y%m%d_%H%M%S")
    image = cv2.imdecode(np.fromfile(photo_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    return analyze_image_data(
        image,
        detector=detector,
        parser=parser,
        source_path=photo_path,
        observed_at=observed_at,
        config=config,
    )


def trend_axis_date_format(results):
    dates = pd.to_datetime([row["datetime"] for row in results], errors="coerce")
    dates = pd.Index(dates.dropna())
    if dates.empty:
        return "%Y-%m-%d"
    if dates.normalize().nunique() == 1:
        return "%H:%M"
    return "%Y-%m-%d"


def compute_trend_series(results):
    df = pd.DataFrame(results)
    if df.empty:
        return pd.Series(dtype="datetime64[ns]"), pd.Series(dtype="float64")

    df["date"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.dropna(subset=["date", "score"]).sort_values("date")
    if df.empty:
        return pd.Series(dtype="datetime64[ns]"), pd.Series(dtype="float64")

    single_day = df["date"].dt.normalize().nunique() == 1
    window = "30min" if single_day else "1D"
    gap_limit = pd.Timedelta(minutes=30) if single_day else pd.Timedelta(hours=12)
    segment_ids = (df["date"].diff() > gap_limit).cumsum()

    smooth_parts = []
    date_parts = []
    for _, segment in df.groupby(segment_ids):
        indexed = segment.set_index("date")
        segment_smooth = indexed["score"].rolling(window=window, min_periods=1, center=True).mean()
        segment_count = indexed["score"].rolling(window=window, min_periods=1, center=True).count()
        segment_smooth[segment_count < 3] = np.nan
        date_parts.append(pd.Series(indexed.index))
        smooth_parts.append(segment_smooth)

    return pd.concat(date_parts, ignore_index=True), pd.concat(smooth_parts, ignore_index=True)


def filter_stable_trend_points(
    results,
    lr_gap_threshold: float = 20.0,
    jump_threshold: float = 25.0,
    local_window: int = 5,
    local_deviation_threshold: float = 18.0,
):
    df = pd.DataFrame(results)
    if df.empty:
        return []

    df["date"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.dropna(subset=["date", "score"]).sort_values("date").copy()
    if df.empty:
        return []

    score_left = df["score_left"] if "score_left" in df.columns else df["score"]
    score_right = df["score_right"] if "score_right" in df.columns else df["score"]
    df["lr_gap"] = (score_left - score_right).abs()
    stable_mask = df["lr_gap"] <= lr_gap_threshold

    local_median = df["score"].rolling(window=local_window, center=True, min_periods=3).median()
    deviation = (df["score"] - local_median).abs()
    stable_mask &= local_median.isna() | (deviation <= local_deviation_threshold)

    prev_gap = df["score"].diff().abs()
    next_gap = df["score"].diff(-1).abs()
    isolated_spike = (prev_gap > jump_threshold) & (next_gap > jump_threshold)
    stable_mask &= ~isolated_spike.fillna(False)

    filtered = df[stable_mask].copy()
    if filtered.empty:
        return df.drop(columns=["date", "lr_gap"]).to_dict("records")
    return filtered.drop(columns=["date", "lr_gap"]).to_dict("records")


def filter_report_outlier_points(
    results,
    lr_gap_threshold: float = 20.0,
    jump_threshold: float = 25.0,
    neighbor_similarity_threshold: float = 12.0,
    local_window: int = 5,
    local_deviation_threshold: float = 18.0,
    segment_gap_minutes: float = 30.0,
):
    df = pd.DataFrame(results)
    if df.empty:
        return []

    df["date"] = pd.to_datetime(df.get("datetime"), errors="coerce")
    if "timestamp" not in df.columns:
        df["timestamp"] = df["date"].apply(lambda value: value.timestamp() if pd.notna(value) else np.nan)

    df = df.dropna(subset=["date", "timestamp", "score"]).sort_values("date").copy()
    if df.empty:
        return []

    score_left = df["score_left"] if "score_left" in df.columns else df["score"]
    score_right = df["score_right"] if "score_right" in df.columns else df["score"]
    df["lr_gap"] = (score_left - score_right).abs()
    keep_mask = df["lr_gap"] <= lr_gap_threshold

    gap_limit = pd.Timedelta(minutes=segment_gap_minutes)
    df["segment_id"] = (df["date"].diff() > gap_limit).cumsum()

    for _, segment in df.groupby("segment_id"):
        if len(segment) < 3:
            continue

        scores = segment["score"]
        prev_gap = scores.diff().abs()
        next_gap = scores.diff(-1).abs()
        neighbor_gap = (scores.shift(-1) - scores.shift(1)).abs()
        local_median = scores.rolling(window=local_window, center=True, min_periods=3).median()
        local_dev = (scores - local_median).abs()

        isolated_spike = (
            prev_gap >= jump_threshold
        ) & (
            next_gap >= jump_threshold
        ) & (
            neighbor_gap <= neighbor_similarity_threshold
        ) & (
            local_median.notna()
        ) & (
            local_dev >= local_deviation_threshold
        )

        keep_mask.loc[segment.index] &= ~isolated_spike.fillna(False)

    filtered = df[keep_mask].copy()
    if filtered.empty:
        return df.drop(columns=["date", "lr_gap", "segment_id"]).to_dict("records")
    return filtered.drop(columns=["date", "lr_gap", "segment_id"]).to_dict("records")


def plot_trend(results, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(results)
    if df.empty:
        return ""

    df["date"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("date")

    plt.figure(figsize=(12, 6))
    plt.scatter(df["date"], df["score"], alpha=0.3, s=15, linewidths=0, label="Raw Score")

    trend_dates, sample_ma = compute_trend_series(results)
    plt.plot(
        trend_dates,
        sample_ma,
        color="#E15759",
        linewidth=1.8,
        alpha=0.95,
        label="Sample Moving Average",
    )
    plt.title(f"Dark Circle Severity Trend (Valid Samples={len(df)})")
    plt.ylabel("Severity Score")
    plt.grid(True, alpha=0.25)
    plt.legend()
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter(trend_axis_date_format(results)))
    plt.gcf().autofmt_xdate()

    output_path = output_dir / "dark_circles_trend.png"
    plt.savefig(output_path, dpi=120, bbox_inches="tight")
    plt.close()
    return str(output_path.resolve())


def empty_trend_views():
    return {
        key: {
            "label": label,
            "points": [],
        }
        for key, label in TREND_VIEW_LABELS.items()
    }


def _trend_points_from_df(df):
    if df.empty:
        return []

    points = []
    for row in df.itertuples(index=False):
        timestamp = getattr(row, "timestamp", None)
        observed_at = getattr(row, "date", None)
        score = getattr(row, "score", None)
        if pd.isna(timestamp) or pd.isna(score) or pd.isna(observed_at):
            continue
        points.append(
            {
                "timestamp": float(timestamp),
                "datetime": observed_at.strftime("%Y-%m-%d %H:%M:%S"),
                "score": round(float(score), 4),
            }
        )
    return points


def _aggregate_daily_scores(df):
    if df.empty:
        return df

    daily = (
        df.assign(day=df["date"].dt.normalize())
        .groupby("day", as_index=False)
        .agg(score=("score", "mean"))
        .rename(columns={"day": "date"})
    )
    daily["timestamp"] = daily["date"].apply(lambda value: value.timestamp())
    return daily[["date", "timestamp", "score"]]


def build_trend_views(results):
    df = pd.DataFrame(results)
    if df.empty:
        return empty_trend_views()

    df["date"] = pd.to_datetime(df.get("datetime"), errors="coerce")
    if "timestamp" not in df.columns:
        df["timestamp"] = df["date"].apply(lambda value: value.timestamp() if pd.notna(value) else np.nan)

    df = df.dropna(subset=["date", "timestamp", "score"]).sort_values("date").copy()
    if df.empty:
        return empty_trend_views()

    latest_date = df["date"].max()
    windows = {
        "day": (latest_date - pd.Timedelta(hours=24), False),
        "week": (latest_date - pd.Timedelta(days=7), True),
        "month": (latest_date - pd.Timedelta(days=30), True),
        "all": (None, True),
    }

    trend_views = empty_trend_views()
    for key, (cutoff, aggregate_daily) in windows.items():
        subset = df if cutoff is None else df[df["date"] >= cutoff]
        subset = subset.sort_values("date")
        if aggregate_daily:
            subset = _aggregate_daily_scores(subset)
        trend_views[key]["points"] = _trend_points_from_df(subset)

    return trend_views


def build_face_report(results, output_dir):
    valid_rows = [row for row in results if row.get("passed") and row.get("score") is not None]
    failed_rows = [row for row in results if not row.get("passed")]
    fail_counts = Counter(reason for row in failed_rows for reason in row.get("fail_reason", []))

    if not valid_rows:
        return {
            "count": 0,
            "quality": {
                "passed": 0,
                "failed": len(failed_rows),
                "fail_reason_counts": dict(fail_counts),
            },
        }

    valid_rows = sorted(valid_rows, key=lambda row: row["timestamp"])
    filtered_rows = filter_report_outlier_points(valid_rows)
    filtered_outlier_count = max(0, len(valid_rows) - len(filtered_rows))

    filtered_rows = sorted(filtered_rows, key=lambda row: row["score"])
    lightest = filtered_rows[0]
    heaviest = filtered_rows[-1]
    trend_plot_path = plot_trend(filtered_rows, output_dir)

    return {
        "count": len(filtered_rows),
        "heaviest": {
            "path": heaviest["path"],
            "score": heaviest["score"],
            "date": heaviest["datetime"],
        },
        "lightest": {
            "path": lightest["path"],
            "score": lightest["score"],
            "date": lightest["datetime"],
        },
        "trend_plot_path": trend_plot_path,
        "trend_views": build_trend_views(filtered_rows),
        "quality": {
            "passed": len(filtered_rows),
            "failed": len(failed_rows),
            "filtered_outliers": filtered_outlier_count,
            "fail_reason_counts": dict(fail_counts),
        },
    }


def export_valid_results_to_excel(results, output_path):
    df = pd.DataFrame([row for row in results if row.get("passed") and row.get("score") is not None])
    if df.empty:
        return None

    columns = [
        "datetime",
        "score",
        "score_left",
        "score_right",
        "delta_e_left",
        "delta_e_right",
        "delta_l_left",
        "delta_l_right",
        "path",
    ]
    existing = [column for column in columns if column in df.columns]
    df = df[existing]
    df.to_excel(output_path, index=False)
    return output_path

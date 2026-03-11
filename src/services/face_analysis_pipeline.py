import os
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


class MediaPipeFaceDetector:
    def __init__(self, min_detection_confidence: float = 0.5):
        import mediapipe as mp

        self._mp = mp
        self._detector = mp.solutions.face_detection.FaceDetection(
            model_selection=1,
            min_detection_confidence=min_detection_confidence,
        )

    def detect(self, image_bgr):
        if image_bgr is None or image_bgr.size == 0:
            return None

        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        results = self._detector.process(rgb)
        if not results.detections:
            return None

        h, w = image_bgr.shape[:2]
        best_bbox = None
        best_score = -1.0

        for detection in results.detections:
            score = float(detection.score[0]) if detection.score else 0.0
            bbox = detection.location_data.relative_bounding_box
            x = max(0, int(bbox.xmin * w))
            y = max(0, int(bbox.ymin * h))
            bw = min(w - x, int(bbox.width * w))
            bh = min(h - y, int(bbox.height * h))
            if bw <= 0 or bh <= 0:
                continue
            if score > best_score:
                best_score = score
                best_bbox = (x, y, bw, bh)

        return best_bbox


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
        import mediapipe as mp

        self.mp_face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
        )

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
        if not hasattr(self, "mp_face_mesh"):
            self._init_fallback()
        if img_bgr.shape[:2] != (512, 512):
            _, resized = self.preprocess(img_bgr)
        else:
            resized = img_bgr
        return self._infer_fallback(resized)

    def _infer_fallback(self, resized):
        h, w = resized.shape[:2]
        parsing_map = np.zeros((h, w), dtype=np.uint8)
        results = self.mp_face_mesh.process(cv2.cvtColor(resized, cv2.COLOR_BGR2RGB))
        if not results.multi_face_landmarks:
            return parsing_map

        landmarks = results.multi_face_landmarks[0].landmark

        def to_pts(indices):
            pts = []
            for idx in indices:
                pt = landmarks[idx]
                pts.append((int(pt.x * w), int(pt.y * h)))
            return np.array(pts, dtype=np.int32)

        face_oval = [
            10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365,
            379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93,
            234, 127, 162, 21, 54, 103, 67, 109,
        ]
        left_eye = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398]
        right_eye = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]

        cv2.fillPoly(parsing_map, [to_pts(face_oval)], CLASS_IDX["skin"])
        cv2.fillPoly(parsing_map, [to_pts(left_eye)], CLASS_IDX["l_eye"])
        cv2.fillPoly(parsing_map, [to_pts(right_eye)], CLASS_IDX["r_eye"])
        return parsing_map


def discover_photo_search_paths():
    onedrive_path = os.environ.get("OneDrive", os.path.expanduser("~\\OneDrive"))
    user_home = os.path.expanduser("~")
    potential_roots = [
        "D:\\WANGBIAO",
        onedrive_path,
        os.path.join(user_home, "OneDrive"),
        user_home,
    ]
    subdirs = [
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


def _analyze_eye_region(parsing_map, resized_img, eye_class_idx, skin_mask, config: AnalysisConfig):
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

    lab = cv2.cvtColor(resized_img, cv2.COLOR_BGR2LAB).astype(np.float32)
    under_pixels = lab[under_mask == 1]
    cheek_pixels = lab[cheek_mask == 1]
    under_med = np.median(under_pixels, axis=0)
    cheek_med = np.median(cheek_pixels, axis=0)

    delta_l = max(0.0, float(cheek_med[0] - under_med[0]))
    delta_e = float(np.linalg.norm(cheek_med - under_med))
    score = (config.score_delta_e_weight * delta_e) + (config.score_delta_l_weight * delta_l)

    return {
        "score": score,
        "delta_l": delta_l,
        "delta_e": delta_e,
        "under_mask_pixels": int(cv2.countNonZero(under_mask)),
        "cheek_mask_pixels": int(cv2.countNonZero(cheek_mask)),
        "under_l": float(under_med[0]),
        "cheek_l": float(cheek_med[0]),
        "eye_box": (ex, ey, ew, eh),
    }


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

    if min(left_metrics["under_mask_pixels"], right_metrics["under_mask_pixels"]) < config.min_under_eye_pixels:
        fail_reasons.append("UnderEyePixelsTooSmall")

    if abs(left_metrics["score"] - right_metrics["score"]) > config.max_left_right_score_gap:
        fail_reasons.append("UnstableLeftRightGap")

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

    left_metrics = _analyze_eye_region(parsing_map, resized_img, CLASS_IDX["l_eye"], skin_mask, config)
    right_metrics = _analyze_eye_region(parsing_map, resized_img, CLASS_IDX["r_eye"], skin_mask, config)

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

    valid_rows = sorted(valid_rows, key=lambda row: row["score"])
    lightest = valid_rows[0]
    heaviest = valid_rows[-1]
    trend_plot_path = plot_trend(valid_rows, output_dir)

    return {
        "count": len(valid_rows),
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
        "quality": {
            "passed": len(valid_rows),
            "failed": len(failed_rows),
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

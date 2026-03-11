import argparse
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from src.services.face_analysis_pipeline import (
    AnalysisConfig,
    CLASS_IDX,
    FaceParser,
    MediaPipeFaceDetector,
    _analyze_eye_region,
    detect_face_crop,
    discover_photo_search_paths,
)
from src.services.face_pipeline_markdown import write_pipeline_markdown


RESULTS_FILE = Path("history") / "face_analysis_results_v2.csv"
DEFAULT_MODEL_PATH = Path("src") / "scripts" / "models" / "face_parsing.farl.lapa.int8.onnx"


def load_latest_passed_path():
    if RESULTS_FILE.exists():
        df = pd.read_csv(RESULTS_FILE)
        df = df[df["passed"] == True]
        if not df.empty:
            return str(df.iloc[-1]["path"])

    for root in reversed(discover_photo_search_paths()):
        files = sorted(Path(root).rglob("photo_*.jpg"))
        if files:
            return str(files[-1])
    raise FileNotFoundError("No photo sample available.")


def save_image(path: Path, image_bgr):
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".jpg", image_bgr)[1].tofile(str(path))


def render_detection_overlay(image_bgr, bbox):
    output = image_bgr.copy()
    x, y, w, h = bbox
    cv2.rectangle(output, (x, y), (x + w, y + h), (0, 255, 255), 8)
    cv2.putText(output, "Face Detection", (x, max(60, y - 20)), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 255, 255), 4)
    return output


def render_parsing_overlay(resized_img, parsing_map):
    overlay = resized_img.copy()
    overlay[parsing_map == CLASS_IDX["skin"]] = [60, 220, 60]
    overlay[parsing_map == CLASS_IDX["l_eye"]] = [255, 120, 0]
    overlay[parsing_map == CLASS_IDX["r_eye"]] = [0, 160, 255]
    return cv2.addWeighted(resized_img, 0.65, overlay, 0.35, 0)


def build_roi_masks(parsing_map, skin_mask, eye_class_idx, config: AnalysisConfig):
    eye_mask = (parsing_map == eye_class_idx).astype(np.uint8)
    coords = cv2.findNonZero(eye_mask)
    if coords is None:
        return None, None
    ex, ey, ew, eh = cv2.boundingRect(coords)
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
    return under_mask, cheek_mask


def render_roi_overlay(resized_img, left_under, left_cheek, right_under, right_cheek):
    overlay = resized_img.copy()
    if left_under is not None:
        overlay[left_under == 1] = [0, 0, 255]
    if left_cheek is not None:
        overlay[left_cheek == 1] = [0, 255, 0]
    if right_under is not None:
        overlay[right_under == 1] = [255, 0, 0]
    if right_cheek is not None:
        overlay[right_cheek == 1] = [0, 255, 255]
    return cv2.addWeighted(resized_img, 0.65, overlay, 0.35, 0)


def generate_walkthrough(sample_path: str, output_dir: Path, model_path: Path):
    config = AnalysisConfig()
    detector = MediaPipeFaceDetector(min_detection_confidence=0.3)
    parser = FaceParser(str(model_path))

    image = cv2.imdecode(np.fromfile(sample_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Failed to read image: {sample_path}")

    bbox = detector.detect(image)
    if not bbox:
        raise RuntimeError("No face detected for the selected sample.")

    crop, crop_error, _ = detect_face_crop(image, detector, config)
    if crop is None:
        raise RuntimeError(f"Face crop failed: {crop_error}")

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    blur_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    parsing_map, resized_img = parser.infer(crop)
    if int(np.count_nonzero(parsing_map == CLASS_IDX["l_eye"])) == 0 or int(np.count_nonzero(parsing_map == CLASS_IDX["r_eye"])) == 0:
        fallback_map = parser.infer_fallback(resized_img)
        parsing_map[fallback_map == CLASS_IDX["l_eye"]] = CLASS_IDX["l_eye"]
        parsing_map[fallback_map == CLASS_IDX["r_eye"]] = CLASS_IDX["r_eye"]
        parsing_map[fallback_map == CLASS_IDX["skin"]] = CLASS_IDX["skin"]

    skin_mask = (parsing_map == CLASS_IDX["skin"]).astype(np.uint8)
    left_metrics = _analyze_eye_region(parsing_map, resized_img, CLASS_IDX["l_eye"], skin_mask, config)
    right_metrics = _analyze_eye_region(parsing_map, resized_img, CLASS_IDX["r_eye"], skin_mask, config)

    fail_reasons = []
    if blur_variance < config.blur_threshold:
        fail_reasons.append(f"Blurry({int(blur_variance)})")
    if left_metrics is None:
        fail_reasons.append("LeftEyeROIInvalid")
    if right_metrics is None:
        fail_reasons.append("RightEyeROIInvalid")

    left_under, left_cheek = build_roi_masks(parsing_map, skin_mask, CLASS_IDX["l_eye"], config)
    right_under, right_cheek = build_roi_masks(parsing_map, skin_mask, CLASS_IDX["r_eye"], config)

    asset_dir = output_dir / "assets"
    original_asset = asset_dir / "original.jpg"
    detection_asset = asset_dir / "detection.jpg"
    crop_asset = asset_dir / "crop.jpg"
    parsing_asset = asset_dir / "parsing.jpg"
    roi_asset = asset_dir / "roi.jpg"

    preview = image.copy()
    scale = min(1600 / preview.shape[1], 1200 / preview.shape[0], 1.0)
    if scale < 1.0:
        preview = cv2.resize(preview, (int(preview.shape[1] * scale), int(preview.shape[0] * scale)))
        scaled_bbox = [int(v * scale) for v in bbox]
    else:
        scaled_bbox = list(bbox)

    save_image(original_asset, preview)
    save_image(detection_asset, render_detection_overlay(preview, scaled_bbox))
    save_image(crop_asset, crop)
    save_image(parsing_asset, render_parsing_overlay(resized_img, parsing_map))
    save_image(roi_asset, render_roi_overlay(resized_img, left_under, left_cheek, right_under, right_cheek))

    data = {
        "sample_title": Path(sample_path).name,
        "source_path": sample_path,
        "status": "passed" if not fail_reasons else "failed",
        "fail_reasons": fail_reasons,
        "assets": {
            "original": "assets/original.jpg",
            "detection": "assets/detection.jpg",
            "crop": "assets/crop.jpg",
            "parsing": "assets/parsing.jpg",
            "roi": "assets/roi.jpg",
        },
        "metrics": {
            "bbox": list(bbox),
            "crop_size": list(crop.shape[:2]),
            "blur_variance": round(blur_variance, 2),
            "skin_pixels": int(np.count_nonzero(parsing_map == CLASS_IDX["skin"])),
            "left_eye_pixels": int(np.count_nonzero(parsing_map == CLASS_IDX["l_eye"])),
            "right_eye_pixels": int(np.count_nonzero(parsing_map == CLASS_IDX["r_eye"])),
            "score_left": None if left_metrics is None else round(left_metrics["score"], 2),
            "score_right": None if right_metrics is None else round(right_metrics["score"], 2),
            "score": None if left_metrics is None or right_metrics is None else round((left_metrics["score"] + right_metrics["score"]) / 2.0, 2),
            "delta_e_left": None if left_metrics is None else round(left_metrics["delta_e"], 2),
            "delta_e_right": None if right_metrics is None else round(right_metrics["delta_e"], 2),
            "delta_l_left": None if left_metrics is None else round(left_metrics["delta_l"], 2),
            "delta_l_right": None if right_metrics is None else round(right_metrics["delta_l"], 2),
        },
    }

    markdown_path = write_pipeline_markdown(data, output_dir / "pipeline.md")
    (output_dir / "pipeline.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return markdown_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", help="Optional sample image path.")
    parser.add_argument("--output-dir", default="output/face_pipeline_walkthrough", help="Output directory for markdown and assets.")
    parser.add_argument("--model", default=str(DEFAULT_MODEL_PATH), help="Face parsing ONNX model path.")
    args = parser.parse_args()

    sample_path = args.path or load_latest_passed_path()
    output_path = generate_walkthrough(sample_path, Path(args.output_dir), Path(args.model))
    print(f"MARKDOWN_PATH:{output_path}")


if __name__ == "__main__":
    main()

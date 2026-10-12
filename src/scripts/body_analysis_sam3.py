"""Local-only, optional SAM3 image analysis runner.

The desktop backend invokes this standalone file with a separate Python
environment. Importing the module never imports GPU dependencies.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath
from statistics import median
from typing import Any, Callable


SCHEMA_VERSION = 1
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"})
ASSET_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})


def discover_images(source_dir: Path) -> list[Path]:
    """Find supported local photos without following links outside the source."""
    source_dir = Path(source_dir)
    if source_dir.is_symlink() or not source_dir.is_dir():
        raise ValueError("source directory unavailable")
    return sorted(
        path for path in source_dir.rglob("*")
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in IMAGE_SUFFIXES
        and not any(parent.is_symlink() for parent in path.parents if parent != source_dir)
    )


def read_capture_time(path: Path) -> tuple[str, str, bool]:
    """Use camera EXIF when available; mtime is display-only, never a trend date."""
    from PIL import ExifTags, Image

    with Image.open(path) as image:
        exif = image.getexif()
        tags = {ExifTags.TAGS.get(key, key): value for key, value in exif.items()}
        if hasattr(exif, "get_ifd"):
            nested = exif.get_ifd(34665)
            tags.update({ExifTags.TAGS.get(key, key): value for key, value in nested.items()})
    for tag in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
        value = tags.get(tag)
        if not value:
            continue
        for form in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(str(value).strip(), form).isoformat(timespec="seconds"), tag, tag == "DateTimeOriginal"
            except ValueError:
                continue
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"), "file_mtime", False


def create_new_output(staging_root: Path, output_dir: Path) -> Path:
    """Create exactly one fresh run directory below a caller-created root."""
    root = Path(staging_root)
    output = Path(output_dir)
    if root.is_symlink():
        raise ValueError("staging root is a symlink")
    if not root.is_dir():
        raise ValueError("staging root unavailable")
    if output.parent != root or output.name in ("", ".", ".."):
        raise ValueError("output must be a direct child of staging root")
    if output.exists() or output.is_symlink():
        raise ValueError("output must be new")
    try:
        output.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise ValueError("output must be new") from exc
    return output


def write_progress(destination: Path, *, status: str, completed: int, total: int) -> None:
    """Atomically publish only bounded job counters, never photo paths."""
    if status not in {"running", "succeeded", "failed"}:
        raise ValueError("invalid progress status")
    if not isinstance(completed, int) or not isinstance(total, int) or not 0 <= completed <= total:
        raise ValueError("invalid progress counters")
    destination = Path(destination)
    if not destination.parent.is_dir() or destination.is_symlink():
        raise ValueError("progress destination unavailable")
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps({"status": status, "completed": completed, "total": total}, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _normalize_gray(rgb: Any) -> Any:
    import cv2
    import numpy as np

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    blurred = np.maximum(cv2.GaussianBlur(gray, (0, 0), sigmaX=35, sigmaY=35), 8)
    normalized = cv2.divide(gray, blurred, scale=128)
    return cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8)).apply(normalized)


def _hair_components(rgb: Any, roi: Any) -> tuple[Any, Any, int]:
    """Extract the prototype's fixed-threshold dark-line proxy, not hair roots."""
    import cv2
    import numpy as np
    from skimage.morphology import skeletonize

    gray = _normalize_gray(rgb)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    response = cv2.subtract(cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel), gray)
    candidate = ((response >= 12) & (roi > 0)).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(candidate, 8)
    filtered = np.zeros_like(candidate)
    height, width = candidate.shape
    for component in range(1, n):
        _, _, w, h, area = stats[component]
        longest, shortest = max(w, h), max(1, min(w, h))
        if area < 3 or area > max(900, height * width * 0.004) or longest < 5:
            continue
        if longest / shortest < 1.35 and area < 14:
            continue
        if area / max(1, w * h) > 0.72 and area > 35:
            continue
        filtered[labels == component] = 1
    inner = cv2.distanceTransform((roi > 0).astype(np.uint8), cv2.DIST_L2, 3) > 4.0
    filtered &= inner.astype(np.uint8)
    skeleton = skeletonize(filtered > 0).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(skeleton, 8)
    lines = np.zeros_like(skeleton)
    count = 0
    for component in range(1, n):
        _, _, w, h, length = stats[component]
        longest, shortest = max(w, h), max(1, min(w, h))
        if length < 8 or longest < 7 or length > 750:
            continue
        if longest / shortest < 1.20 and length < 18:
            continue
        lines[labels == component] = 1
        count += 1
    return filtered, lines, count


def _save_mask_and_overlay(rgb: Any, mask: Any, report_dir: Path, prefix: str) -> tuple[str, str]:
    import numpy as np
    from PIL import Image

    masks = report_dir / "masks"
    overlays = report_dir / "overlays"
    masks.mkdir(exist_ok=True)
    overlays.mkdir(exist_ok=True)
    mask_path = f"masks/{prefix}.png"
    overlay_path = f"overlays/{prefix}.jpg"
    Image.fromarray((mask > 0).astype(np.uint8) * 255).save(report_dir / mask_path)
    overlay = rgb.copy()
    tint = np.array((32, 180, 209), dtype=np.uint8)
    overlay[mask > 0] = (overlay[mask > 0] * 0.58 + tint * 0.42).astype(np.uint8)
    Image.fromarray(overlay).save(report_dir / overlay_path, quality=88)
    return mask_path, overlay_path


def analyze_photo(
    photo: Path,
    kind: str,
    report_dir: Path,
    index: int,
    segment: Callable[[Any, str], tuple[Any, list[float]]],
) -> dict[str, Any]:
    """Analyze one photo through an injected local SAM3 segmenter."""
    import cv2
    import numpy as np
    from PIL import Image, ImageOps

    if kind not in {"leg", "scalp"}:
        raise ValueError("unknown analysis kind")
    photo = Path(photo)
    report_dir = Path(report_dir)
    with Image.open(photo) as image:
        rgb = np.asarray(ImageOps.exif_transpose(image).convert("RGB"))
    height, width = rgb.shape[:2]
    scale = min(1.0, 1600 / max(height, width))
    if scale < 1.0:
        rgb = cv2.resize(rgb, (max(1, round(width * scale)), max(1, round(height * scale))), interpolation=cv2.INTER_AREA)
    capture, timestamp_source, verified = read_capture_time(photo)
    primary, scores = segment(rgb, "bare leg" if kind == "leg" else "hair")
    primary = (np.asarray(primary) > 0).astype(np.uint8)
    if primary.shape != rgb.shape[:2]:
        raise ValueError("segmentation size mismatch")
    area = int(primary.sum())
    binary, lines, count = _hair_components(rgb, primary) if area else (
        np.zeros_like(primary), np.zeros_like(primary), 0
    )
    prefix = f"{kind}-{index:04d}"
    mask_path, overlay_path = _save_mask_and_overlay(rgb, primary, report_dir, prefix)
    texture_path, texture_overlay_path = _save_mask_and_overlay(rgb, binary, report_dir, f"{prefix}-texture")
    line_mask_path, line_overlay_path = _save_mask_and_overlay(rgb, lines, report_dir, f"{prefix}-lines")
    sharpness = float(cv2.Laplacian(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), cv2.CV_64F).var())
    quality = ["automatic segmentation requires visual review"]
    if not verified:
        quality.append("no camera capture time; excluded from trends")
    if area < primary.size * 0.03:
        quality.append("target missing or too small")
    if scores and min(scores) < 0.7:
        quality.append("low model score in part of target")
    if sharpness < 35:
        quality.append("low image sharpness")
    record: dict[str, Any] = {
        "kind": kind, "file_name": photo.name, "captured_at": capture,
        "timestamp_source": timestamp_source, "timestamp_verified": verified,
        "analysis_width": int(rgb.shape[1]), "analysis_height": int(rgb.shape[0]),
        "roi_area_px": area, "roi_area_ratio": float(area / primary.size),
        "sam_scores": [float(score) for score in scores], "sharpness": sharpness,
        "quality_flags": quality, "review_status": "unreviewed", "trend_eligible": False,
        "mask_path": mask_path, "overlay_path": overlay_path,
        "texture_mask_path": texture_path, "texture_overlay_path": texture_overlay_path,
        "line_mask_path": line_mask_path, "line_overlay_path": line_overlay_path,
        "texture_fraction_percent": float(binary.sum() / area * 100) if area else None,
    }
    if kind == "leg":
        record["hair_count"] = count if area else None
        record["hair_density_per_mpx"] = float(count / (area / 1e6)) if area else None
        return record

    secondary, secondary_scores = segment(rgb, "scalp")
    secondary = (np.asarray(secondary) > 0).astype(np.uint8)
    if secondary.shape != primary.shape:
        raise ValueError("segmentation size mismatch")
    candidate_mask_path, candidate_overlay_path = _save_mask_and_overlay(
        rgb, secondary, report_dir, f"{prefix}-scalp-candidate"
    )
    union = (primary > 0) | (secondary > 0)
    exposed = (secondary > 0) & (primary == 0)
    record.update({
        "hair_region_fraction_percent": float(area / primary.size * 100) if area else None,
        "scalp_candidate_fraction_percent": float(exposed.sum() / union.sum() * 100)
        if area and union.any() and secondary.any() else None,
        "scalp_sam_scores": [float(score) for score in secondary_scores],
        "scalp_candidate_mask_path": candidate_mask_path,
        "scalp_candidate_overlay_path": candidate_overlay_path,
        "scalp_candidate_review_status": "rejected",
    })
    quality.append("scalp candidate is unvalidated and excluded from trends")
    return record


def aggregate_trends(records: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """Only manually accepted, EXIF-dated, complete proxies can enter trends."""
    if kind not in {"leg", "scalp"}:
        raise ValueError("unknown analysis kind")
    metrics = ("hair_count", "hair_density_per_mpx") if kind == "leg" else (
        "hair_region_fraction_percent", "texture_fraction_percent"
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("kind") != kind or record.get("review_status") != "accepted":
            continue
        if not record.get("trend_eligible") or not record.get("timestamp_verified"):
            continue
        if any(not isinstance(record.get(metric), (int, float)) or not math.isfinite(record[metric]) for metric in metrics):
            continue
        grouped[str(record["captured_at"])[:10]].append(record)
    return [
        {"date": day, **{metric: float(median(record[metric] for record in group)) for metric in metrics}, "n": len(group)}
        for day, group in sorted(grouped.items())
    ]


def _record_assets(record: dict[str, Any]) -> list[str]:
    return [value for key, value in record.items() if key.endswith("_path") and isinstance(value, str)]


def build_report(leg_records: list[dict[str, Any]], scalp_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Construct a complete machine-readable report; no raw image is copied."""
    return {
        "schema_version": SCHEMA_VERSION, "complete": True, "engine": "sam3",
        "input_counts": {"leg": len(leg_records), "scalp": len(scalp_records)},
        "leg": {"records": leg_records, "trend": aggregate_trends(leg_records, "leg")},
        "scalp": {"records": scalp_records, "trend": aggregate_trends(scalp_records, "scalp")},
        "assets": sorted(set(path for record in leg_records + scalp_records for path in _record_assets(record))),
    }


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_record(record: Any, kind: str, assets: set[str]) -> None:
    if not isinstance(record, dict):
        raise ValueError("invalid report record")
    required = {
        "kind", "file_name", "captured_at", "timestamp_source", "timestamp_verified",
        "analysis_width", "analysis_height", "roi_area_px", "roi_area_ratio",
        "sam_scores", "sharpness", "quality_flags", "review_status", "trend_eligible",
        "mask_path", "overlay_path", "texture_mask_path", "texture_overlay_path",
        "line_mask_path", "line_overlay_path", "texture_fraction_percent",
    }
    required |= {"hair_count", "hair_density_per_mpx"} if kind == "leg" else {
        "hair_region_fraction_percent", "scalp_candidate_fraction_percent", "scalp_sam_scores",
        "scalp_candidate_mask_path", "scalp_candidate_overlay_path", "scalp_candidate_review_status",
    }
    if not required.issubset(record) or record["kind"] != kind:
        raise ValueError("incomplete report record")
    name = record["file_name"]
    if not isinstance(name, str) or name in {"", ".", ".."} or any(char in name for char in "/\\:"):
        raise ValueError("invalid photo name")
    if not isinstance(record["captured_at"], str):
        raise ValueError("invalid capture time")
    try:
        datetime.fromisoformat(record["captured_at"])
    except ValueError as exc:
        raise ValueError("invalid capture time") from exc
    source = record["timestamp_source"]
    if not isinstance(source, str) or source not in {"DateTimeOriginal", "DateTimeDigitized", "DateTime", "file_mtime"}:
        raise ValueError("invalid capture time source")
    if type(record["timestamp_verified"]) is not bool or record["timestamp_verified"] != (source == "DateTimeOriginal"):
        raise ValueError("invalid capture verification")
    width, height, area = (record[key] for key in ("analysis_width", "analysis_height", "roi_area_px"))
    if any(type(value) is not int for value in (width, height, area)) or width <= 0 or height <= 0 or not 0 <= area <= width * height:
        raise ValueError("invalid analysis dimensions")
    ratio = record["roi_area_ratio"]
    if not _finite_number(ratio) or not math.isclose(ratio, area / (width * height), abs_tol=1e-8):
        raise ValueError("invalid analysis area ratio")
    if not _finite_number(record["sharpness"]) or record["sharpness"] < 0:
        raise ValueError("invalid image sharpness")
    for key in ("sam_scores", "scalp_sam_scores") if kind == "scalp" else ("sam_scores",):
        scores = record[key]
        if not isinstance(scores, list) or any(not _finite_number(score) or not 0 <= score <= 1 for score in scores):
            raise ValueError("invalid model scores")
    flags = record["quality_flags"]
    if not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags):
        raise ValueError("invalid quality flags")
    if not isinstance(record["review_status"], str) or record["review_status"] not in {"unreviewed", "accepted", "rejected"} or type(record["trend_eligible"]) is not bool:
        raise ValueError("invalid review status")
    if record["trend_eligible"] and (record["review_status"] != "accepted" or not record["timestamp_verified"]):
        raise ValueError("unreviewed measurement in trend")
    for key in ("texture_fraction_percent", "hair_region_fraction_percent", "scalp_candidate_fraction_percent"):
        if key in record and record[key] is not None and (not _finite_number(record[key]) or not 0 <= record[key] <= 100):
            raise ValueError("invalid proxy percentage")
    if kind == "leg":
        count, density = record["hair_count"], record["hair_density_per_mpx"]
        if count is not None and (type(count) is not int or count < 0):
            raise ValueError("invalid line count")
        if density is not None and (not _finite_number(density) or density < 0):
            raise ValueError("invalid line density")
        if (area == 0) != (count is None and density is None):
            raise ValueError("invalid missing detection")
        if area == 0 and record["texture_fraction_percent"] is not None:
            raise ValueError("invalid missing detection")
    else:
        if record["scalp_candidate_review_status"] != "rejected":
            raise ValueError("unreviewed scalp candidate")
        if area == 0 and any(record[key] is not None for key in (
            "hair_region_fraction_percent", "texture_fraction_percent", "scalp_candidate_fraction_percent"
        )):
            raise ValueError("invalid missing detection")
    for key in required:
        if key.endswith("_path") and (not isinstance(record[key], str) or record[key] not in assets):
            raise ValueError("unlisted report asset")


def validate_report_manifest(report: dict[str, Any], output_root: Path) -> bool:
    """Fail closed on incomplete reports or any reference outside generated assets."""
    if not isinstance(report, dict) or report.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported report schema")
    if report.get("complete") is not True or report.get("engine") != "sam3":
        raise ValueError("incomplete report")
    for section in ("leg", "scalp"):
        value = report.get(section)
        if not isinstance(value, dict) or not isinstance(value.get("records"), list) or not isinstance(value.get("trend"), list):
            raise ValueError("invalid report section")
    counts = report.get("input_counts")
    if not isinstance(counts, dict) or set(counts) != {"leg", "scalp"}:
        raise ValueError("invalid input counts")
    for section in ("leg", "scalp"):
        if type(counts[section]) is not int or counts[section] < 0 or counts[section] != len(report[section]["records"]):
            raise ValueError("invalid input counts")
    assets = report.get("assets")
    if not isinstance(assets, list) or not all(isinstance(path, str) for path in assets):
        raise ValueError("invalid report assets")
    root = Path(output_root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("report root unavailable")
    for relative in assets:
        if "\\" in relative or ":" in relative or relative.startswith("/"):
            raise ValueError("invalid asset path")
        path = PurePosixPath(relative)
        if not path.parts or path.is_absolute() or ".." in path.parts or path.parts[0] not in {"masks", "overlays"}:
            raise ValueError("invalid asset path")
        if path.suffix.lower() not in ASSET_SUFFIXES:
            raise ValueError("invalid asset type")
        absolute = root.joinpath(*path.parts)
        if any(component.is_symlink() for component in (absolute, *absolute.parents) if component != root):
            raise ValueError("asset symlink forbidden")
        if not absolute.is_file() or not absolute.resolve().is_relative_to(root.resolve()):
            raise ValueError("missing or escaped report asset")
    asset_set = set(assets)
    for section in ("leg", "scalp"):
        for record in report[section]["records"]:
            _validate_record(record, section, asset_set)
        if report[section]["trend"] != aggregate_trends(report[section]["records"], section):
            raise ValueError("invalid report trend")
    return True


def _load_local_segmenter(model_dir: Path) -> Callable[[Any, str], tuple[Any, list[float]]]:
    """Load only an existing local checkpoint; never ask a provider or hub."""
    import numpy as np
    import torch
    from PIL import Image
    from transformers import Sam3Model, Sam3Processor

    if not torch.cuda.is_available():
        raise RuntimeError("cuda_unavailable")
    model = Sam3Model.from_pretrained(str(model_dir), local_files_only=True).to("cuda").eval()
    processor = Sam3Processor.from_pretrained(str(model_dir), local_files_only=True)
    autocast_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16

    def segment(rgb: Any, prompt: str) -> tuple[Any, list[float]]:
        inputs = processor(images=Image.fromarray(rgb), text=prompt, return_tensors="pt").to("cuda")
        with torch.inference_mode(), torch.autocast("cuda", dtype=autocast_dtype):
            output = model(**inputs)
        result = processor.post_process_instance_segmentation(
            output, threshold=0.5, mask_threshold=0.5,
            target_sizes=inputs["original_sizes"].tolist(),
        )[0]
        masks = result["masks"].detach().cpu().numpy().astype(bool)
        union = np.any(masks, axis=0) if len(masks) else np.zeros(rgb.shape[:2], dtype=bool)
        return union.astype(np.uint8), result["scores"].detach().float().cpu().tolist()

    return segment


def run(
    *, leg_dir: Path, scalp_dir: Path, model_dir: Path,
    staging_root: Path, output_dir: Path, progress_json: Path,
) -> Path:
    """Run both configured sources and create a complete staging report."""
    leg_dir, scalp_dir, model_dir = map(Path, (leg_dir, scalp_dir, model_dir))
    staging_root, output_dir, progress_json = map(Path, (staging_root, output_dir, progress_json))
    if not all(path.is_dir() and not path.is_symlink() for path in (leg_dir, scalp_dir, model_dir)):
        raise ValueError("source_or_checkpoint_unavailable")
    if progress_json != output_dir / "progress.json":
        raise ValueError("progress_destination_invalid")
    root = staging_root.resolve()
    if any(root.is_relative_to(source.resolve()) or source.resolve().is_relative_to(root)
           for source in (leg_dir, scalp_dir, model_dir)):
        raise ValueError("source_and_staging_overlap")
    images = {"leg": discover_images(leg_dir), "scalp": discover_images(scalp_dir)}
    segment = _load_local_segmenter(model_dir)
    output = create_new_output(staging_root, output_dir)
    total = sum(len(paths) for paths in images.values())
    completed = 0
    write_progress(progress_json, status="running", completed=0, total=total)
    records: dict[str, list[dict[str, Any]]] = {"leg": [], "scalp": []}
    try:
        for kind in ("leg", "scalp"):
            for index, path in enumerate(images[kind], start=1):
                records[kind].append(analyze_photo(path, kind, output, index, segment))
                completed += 1
                write_progress(progress_json, status="running", completed=completed, total=total)
        report = build_report(records["leg"], records["scalp"])
        validate_report_manifest(report, output)
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        write_progress(progress_json, status="succeeded", completed=completed, total=total)
        return output / "report.json"
    except Exception:
        write_progress(progress_json, status="failed", completed=completed, total=total)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a local SAM3 body-analysis report")
    for option in ("leg-dir", "scalp-dir", "model-dir", "staging-root", "output-dir", "progress-json"):
        parser.add_argument(f"--{option}", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        run(
            leg_dir=args.leg_dir, scalp_dir=args.scalp_dir, model_dir=args.model_dir,
            staging_root=args.staging_root, output_dir=args.output_dir, progress_json=args.progress_json,
        )
    except Exception as exc:
        # Exception messages can include absolute photo paths or checkpoint metadata.
        # The supervising backend receives only a stable, redacted error code.
        code = "prerequisite_unavailable" if isinstance(exc, (ImportError, ModuleNotFoundError)) else "analysis_failed"
        print(code, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

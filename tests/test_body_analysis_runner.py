"""Contract tests for the optional, local-only SAM3 report runner."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image


RUNNER_PATH = Path(__file__).resolve().parents[1] / "src" / "scripts" / "body_analysis_sam3.py"


@pytest.fixture
def runner():
    assert RUNNER_PATH.is_file(), "the standalone SAM3 runner is missing"
    return importlib.import_module("src.scripts.body_analysis_sam3")


def _photo(path: Path, *, exif_time: str | None = None) -> None:
    image = Image.new("RGB", (48, 40), color=(170, 140, 110))
    if exif_time:
        exif = image.getexif()
        exif[36867] = exif_time
        image.save(path, exif=exif)
    else:
        image.save(path)


def test_discover_images_is_sorted_local_and_skips_other_files(tmp_path, runner):
    folder = tmp_path / "photos"
    (folder / "nested").mkdir(parents=True)
    _photo(folder / "b.JPG")
    _photo(folder / "nested" / "a.png")
    (folder / "note.txt").write_text("not a photo")
    outside = tmp_path / "outside.png"
    _photo(outside)
    try:
        (folder / "escape.png").symlink_to(outside)
    except OSError:
        pass

    assert runner.discover_images(folder) == [folder / "b.JPG", folder / "nested" / "a.png"]


def test_capture_time_uses_exif_and_marks_mtime_unverified(tmp_path, runner):
    dated = tmp_path / "dated.jpg"
    _photo(dated, exif_time="2026:01:02 03:04:05")
    captured_at, source, verified = runner.read_capture_time(dated)
    assert (captured_at, source, verified) == ("2026-01-02T03:04:05", "DateTimeOriginal", True)

    undated = tmp_path / "undated.jpg"
    _photo(undated)
    epoch = datetime(2026, 1, 3, 12, 0, 0).timestamp()
    os.utime(undated, (epoch, epoch))
    captured_at, source, verified = runner.read_capture_time(undated)
    assert captured_at.startswith("2026-01-03T12:00:00")
    assert (source, verified) == ("file_mtime", False)


def test_new_output_must_be_direct_child_and_must_not_exist(tmp_path, runner):
    root = tmp_path / "staging"
    root.mkdir()
    output = root / "run-1"
    assert runner.create_new_output(root, output) == output
    assert output.is_dir()
    with pytest.raises(ValueError, match="new"):
        runner.create_new_output(root, output)
    with pytest.raises(ValueError, match="direct child"):
        runner.create_new_output(root, root / "nested" / "run-2")
    with pytest.raises(ValueError, match="direct child"):
        runner.create_new_output(root, tmp_path / "elsewhere")


def test_new_output_rejects_symlink_staging_root(tmp_path, runner):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    with pytest.raises(ValueError, match="symlink"):
        runner.create_new_output(link, link / "run")


def test_no_detection_is_null_and_masks_remain_inspectable(tmp_path, runner):
    import numpy as np

    photo = tmp_path / "leg.jpg"
    _photo(photo, exif_time="2026:01:02 03:04:05")
    report_dir = tmp_path / "report"
    report_dir.mkdir()

    def segment(_image, _prompt):
        return np.zeros((40, 48), dtype=np.uint8), []

    record = runner.analyze_photo(photo, "leg", report_dir, 1, segment)
    assert record["kind"] == "leg"
    assert record["file_name"] == "leg.jpg"
    assert record["hair_count"] is None
    assert record["hair_density_per_mpx"] is None
    assert record["roi_area_px"] == 0
    assert record["review_status"] == "unreviewed"
    assert record["trend_eligible"] is False
    assert (report_dir / record["mask_path"]).is_file()
    assert (report_dir / record["overlay_path"]).is_file()


def test_scalp_candidate_is_visible_but_excluded_from_trend(tmp_path, runner):
    import numpy as np

    photo = tmp_path / "scalp.jpg"
    _photo(photo, exif_time="2026:01:02 03:04:05")
    report_dir = tmp_path / "report"
    report_dir.mkdir()

    def segment(_image, prompt):
        mask = np.zeros((40, 48), dtype=np.uint8)
        mask[8:28, 8:28] = 1 if prompt == "hair" else 0
        if prompt == "scalp":
            mask[10:30, 24:36] = 1
        return mask, [0.9]

    record = runner.analyze_photo(photo, "scalp", report_dir, 1, segment)
    assert record["scalp_candidate_fraction_percent"] is not None
    assert record["scalp_candidate_review_status"] == "rejected"
    assert record["trend_eligible"] is False
    assert (report_dir / record["scalp_candidate_mask_path"]).is_file()
    assert (report_dir / record["scalp_candidate_overlay_path"]).is_file()
    assert runner.aggregate_trends([record], "scalp") == []


def test_trends_require_verified_time_and_accepted_review(runner):
    base = {
        "kind": "leg", "captured_at": "2026-01-02T12:00:00", "timestamp_verified": True,
        "review_status": "accepted", "trend_eligible": True, "hair_count": 12,
        "hair_density_per_mpx": 20.0,
    }
    accepted = dict(base)
    no_exif = dict(base, timestamp_verified=False, hair_count=90)
    rejected = dict(base, review_status="rejected", hair_count=80)
    missing = dict(base, hair_count=None, hair_density_per_mpx=None)
    trend = runner.aggregate_trends([accepted, no_exif, rejected, missing], "leg")
    assert trend == [{"date": "2026-01-02", "hair_count": 12.0, "hair_density_per_mpx": 20.0, "n": 1}]


def test_report_manifest_rejects_traversal_and_symlink_assets(tmp_path, runner):
    report = tmp_path / "report"
    report.mkdir()
    (report / "masks").mkdir()
    (report / "masks" / "1.png").write_bytes(b"png")
    valid = {
        "schema_version": 1, "complete": True, "engine": "sam3",
        "leg": {"records": [], "trend": []}, "scalp": {"records": [], "trend": []},
        "assets": ["masks/1.png"],
    }
    assert runner.validate_report_manifest(valid, report) is True
    for bad in ("", "../outside.png", "/absolute.png", "C:/outside.png", "masks/absent.png"):
        with pytest.raises(ValueError):
            runner.validate_report_manifest(dict(valid, assets=[bad]), report)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"not a report asset")
    try:
        (report / "masks" / "link.png").symlink_to(outside)
    except OSError:
        pass
    else:
        with pytest.raises(ValueError):
            runner.validate_report_manifest(dict(valid, assets=["masks/link.png"]), report)


def test_runner_help_and_invalid_checkpoint_work_without_gpu_dependencies(tmp_path, runner):
    result = subprocess.run([sys.executable, str(RUNNER_PATH), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    for option in ("--leg-dir", "--scalp-dir", "--model-dir", "--staging-root", "--output-dir", "--progress-json"):
        assert option in result.stdout

    leg = tmp_path / "leg"
    scalp = tmp_path / "scalp"
    staging = tmp_path / "staging"
    for folder in (leg, scalp, staging):
        folder.mkdir()
    output = staging / "run"
    result = subprocess.run([
        sys.executable, str(RUNNER_PATH), "--leg-dir", str(leg), "--scalp-dir", str(scalp),
        "--model-dir", str(tmp_path / "missing"), "--staging-root", str(staging),
        "--output-dir", str(output), "--progress-json", str(output / "progress.json"),
    ], capture_output=True, text=True)
    assert result.returncode != 0
    assert not output.exists()
    assert str(tmp_path) not in result.stderr


def test_progress_is_atomic_json_with_no_source_paths(tmp_path, runner):
    output = tmp_path / "run"
    output.mkdir()
    destination = output / "progress.json"
    runner.write_progress(destination, status="running", completed=1, total=3)
    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "status": "running", "completed": 1, "total": 3,
    }
    assert sorted(path.name for path in output.iterdir()) == ["progress.json"]


def test_synthetic_run_writes_complete_report_without_gpu(tmp_path, monkeypatch, runner):
    import numpy as np

    leg, scalp, model, staging = (tmp_path / name for name in ("leg", "scalp", "model", "staging"))
    for folder in (leg, scalp, model, staging):
        folder.mkdir()
    _photo(leg / "one.jpg", exif_time="2026:01:02 03:04:05")
    _photo(scalp / "two.jpg", exif_time="2026:01:03 03:04:05")

    def segment(image, prompt):
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        if prompt != "scalp":
            mask[5:35, 5:40] = 1
        return mask, [0.9]

    monkeypatch.setattr(runner, "_load_local_segmenter", lambda _: segment)
    output = staging / "run"
    report_path = runner.run(
        leg_dir=leg, scalp_dir=scalp, model_dir=model,
        staging_root=staging, output_dir=output, progress_json=output / "progress.json",
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert runner.validate_report_manifest(report, output) is True
    assert len(report["leg"]["records"]) == len(report["scalp"]["records"]) == 1
    assert report["leg"]["trend"] == report["scalp"]["trend"] == []
    assert report["scalp"]["records"][0]["scalp_candidate_fraction_percent"] is None
    assert report["complete"] is True
    assert json.loads((output / "progress.json").read_text())["status"] == "succeeded"
    assert str(tmp_path) not in report_path.read_text(encoding="utf-8")

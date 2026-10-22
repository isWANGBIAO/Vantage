"""Contract tests for the optional, local-only SAM3 report runner."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType

import pytest
from PIL import Image


RUNNER_PATH = Path(__file__).resolve().parents[1] / "src" / "scripts" / "body_analysis_sam3.py"


@pytest.fixture
def runner():
    assert RUNNER_PATH.is_file(), "the standalone SAM3 runner is missing"
    return importlib.import_module("src.scripts.body_analysis_sam3")


@pytest.fixture
def empty_texture_skeleton(monkeypatch):
    """Isolate optional skeletonization only for uniform, texture-free photos.

    These contract tests exercise real ROI handling, component extraction,
    report assets and validation, not scikit-image's thinning algorithm. The
    skeleton of an empty mask is exactly that empty mask. Refuse nonempty
    input so a changed fixture cannot silently bypass the real algorithm.
    """
    morphology = ModuleType("skimage.morphology")

    def skeletonize_empty(mask):
        assert mask.ndim == 2 and mask.dtype.kind == "b"
        assert not mask.any(), "nonempty textures need the real optional skeletonizer"
        return mask.copy()

    morphology.skeletonize = skeletonize_empty
    package = ModuleType("skimage")
    package.__path__ = []
    package.morphology = morphology
    monkeypatch.setitem(sys.modules, "skimage", package)
    monkeypatch.setitem(sys.modules, "skimage.morphology", morphology)


def _photo(path: Path, *, exif_time: str | None = None, exif_tag: int = 36867) -> None:
    image = Image.new("RGB", (48, 40), color=(170, 140, 110))
    if exif_time:
        exif = image.getexif()
        exif[exif_tag] = exif_time
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


def test_discover_images_rejects_resolved_escape_even_if_link_flag_is_missed(tmp_path, monkeypatch, runner):
    folder = tmp_path / "photos"
    folder.mkdir()
    outside = tmp_path / "outside.png"
    _photo(outside)
    escape = folder / "escape.png"
    try:
        escape.symlink_to(outside)
    except OSError:
        pytest.skip("links unavailable")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: False if self == escape else original(self))
    assert runner.discover_images(folder) == []


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


@pytest.mark.parametrize("tag,expected_source", [(36868, "DateTimeDigitized"), (306, "DateTime")])
def test_non_original_exif_dates_are_display_only(tmp_path, runner, tag, expected_source):
    photo = tmp_path / "not-original.jpg"
    _photo(photo, exif_time="2026:02:03 04:05:06", exif_tag=tag)
    captured_at, source, verified = runner.read_capture_time(photo)
    assert (captured_at, source) == ("2026-02-03T04:05:06", expected_source)
    assert verified is False


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


def test_direct_runner_refuses_staging_inside_checkout(tmp_path, runner):
    checkout = Path(__file__).resolve().parents[1]
    for name in ("leg", "scalp", "model"):
        (tmp_path / name).mkdir()
    output = checkout / "runner-must-not-create"
    assert not output.exists()
    with pytest.raises(ValueError, match="repository"):
        runner.run(
            leg_dir=tmp_path / "leg", scalp_dir=tmp_path / "scalp", model_dir=tmp_path / "model",
            staging_root=checkout, output_dir=output, progress_json=output / "progress.json",
        )
    assert not output.exists()


def test_runner_refuses_its_source_tree_even_without_git_metadata(tmp_path, monkeypatch, runner):
    scripts = tmp_path / "src" / "scripts"
    scripts.mkdir(parents=True)
    monkeypatch.setattr(runner, "__file__", str(scripts / "body_analysis_sam3.py"))
    with pytest.raises(ValueError, match="repository"):
        runner.create_new_output(tmp_path, tmp_path / "private-report")
    assert not (tmp_path / "private-report").exists()


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


def test_scalp_candidate_is_visible_but_excluded_from_trend(tmp_path, runner, empty_texture_skeleton):
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
    assert record["texture_fraction_percent"] == 0.0
    assert record["scalp_candidate_fraction_percent"] is not None
    assert record["scalp_candidate_review_status"] == "rejected"
    assert record["trend_eligible"] is False
    assert (report_dir / record["scalp_candidate_mask_path"]).is_file()
    assert (report_dir / record["scalp_candidate_overlay_path"]).is_file()
    assert runner.aggregate_trends([record], "scalp") == []


def test_missing_primary_hair_detection_does_not_imply_full_scalp_visibility(tmp_path, runner):
    import numpy as np

    photo = tmp_path / "scalp.jpg"
    _photo(photo)
    output = tmp_path / "report"
    output.mkdir()

    def segment(image, prompt):
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        if prompt == "scalp":
            mask[5:30, 5:30] = 1
        return mask, [0.9]

    record = runner.analyze_photo(photo, "scalp", output, 1, segment)
    assert record["hair_region_fraction_percent"] is None
    assert record["scalp_candidate_fraction_percent"] is None
    assert (output / record["scalp_candidate_mask_path"]).is_file()


def test_trends_require_verified_time_and_accepted_review(runner):
    base = {
        "kind": "leg", "captured_at": "2026-01-02T12:00:00", "timestamp_verified": True,
        "review_status": "accepted", "trend_eligible": True, "hair_count": 12,
        "hair_density_per_mpx": 20.0, "roi_area_ratio": 0.3,
    }
    accepted = dict(base)
    no_exif = dict(base, timestamp_verified=False, hair_count=90)
    rejected = dict(base, review_status="rejected", hair_count=80)
    missing = dict(base, hair_count=None, hair_density_per_mpx=None)
    trend = runner.aggregate_trends([accepted, no_exif, rejected, missing], "leg")
    assert trend == [{
        "date": "2026-01-02", "hair_count": 12.0, "hair_density_per_mpx": 20.0,
        "n": 1, "measurement_type": "photographic_proxy", "review_status": "accepted",
    }]


def test_unreviewed_leg_proxy_has_trend_only_with_verified_time_and_valid_roi(runner):
    base = {
        "kind": "leg", "captured_at": "2026-01-02T12:00:00", "timestamp_verified": True,
        "review_status": "unreviewed", "trend_eligible": True, "roi_area_ratio": 0.3,
        "hair_count": 4, "hair_density_per_mpx": 40.0,
    }
    invalid = [
        dict(base, timestamp_verified=False), dict(base, roi_area_ratio=0.01),
        dict(base, hair_count=None), dict(base, review_status="rejected"),
    ]
    assert runner.aggregate_trends([base, *invalid], "leg") == [{
        "date": "2026-01-02", "hair_count": 4.0, "hair_density_per_mpx": 40.0,
        "n": 1, "measurement_type": "photographic_proxy", "review_status": "unreviewed",
    }]


def test_report_manifest_rejects_traversal_and_symlink_assets(tmp_path, runner):
    report = tmp_path / "report"
    report.mkdir()
    (report / "masks").mkdir()
    (report / "masks" / "1.png").write_bytes(b"png")
    valid = {
        "schema_version": 1, "complete": True, "engine": "sam3",
        "input_counts": {"leg": 0, "scalp": 0},
        "leg": {"records": [], "trend": [], "trend_unavailable_reason": "no_images"},
        "scalp": {"records": [], "trend": [], "trend_unavailable_reason": "no_images"},
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


def test_manifest_requires_exact_input_counts(tmp_path, runner):
    output = tmp_path / "report"
    output.mkdir()
    valid = runner.build_report([], [])
    assert valid["input_counts"] == {"leg": 0, "scalp": 0}
    assert valid["scalp"]["trend_unavailable_reason"] == "no_images"
    assert runner.validate_report_manifest(valid, output)
    for invalid in (None, {"leg": 1, "scalp": 0}, {"leg": False, "scalp": 0}, {"leg": 0}):
        with pytest.raises(ValueError, match="input counts"):
            runner.validate_report_manifest(dict(valid, input_counts=invalid), output)


def test_manifest_rejects_incomplete_or_wrongly_typed_photo_records(tmp_path, runner, empty_texture_skeleton):
    import numpy as np

    photo = tmp_path / "leg.jpg"
    _photo(photo, exif_time="2026:01:02 03:04:05")
    output = tmp_path / "report"
    output.mkdir()
    record = runner.analyze_photo(
        photo, "leg", output, 1,
        lambda image, _prompt: (np.ones(image.shape[:2], dtype=np.uint8), [0.9]),
    )
    assert record["hair_count"] == 0
    assert record["hair_density_per_mpx"] == 0.0
    valid = runner.build_report([record], [])
    assert runner.validate_report_manifest(valid, output)
    mutations = (
        {key: value for key, value in record.items() if key != "mask_path"},
        dict(record, file_name="../private.jpg"),
        dict(record, timestamp_verified="true"),
        dict(record, roi_area_px="100"),
        dict(record, review_status="accepted", trend_eligible=True, timestamp_verified=False),
        dict(record, overlay_path="masks/not-listed.png"),
    )
    for bad in mutations:
        tampered = dict(valid, leg={"records": [bad], "trend": []})
        with pytest.raises(ValueError):
            runner.validate_report_manifest(tampered, output)


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


def test_synthetic_run_writes_complete_report_without_gpu(tmp_path, monkeypatch, runner, empty_texture_skeleton):
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
    leg_record = report["leg"]["records"][0]
    assert leg_record["hair_count"] == 0
    assert leg_record["texture_fraction_percent"] == 0.0
    for field in ("texture_mask_path", "line_mask_path"):
        with Image.open(output / leg_record[field]) as mask:
            assert mask.getextrema() == (0, 0)
    assert len(report["leg"]["trend"]) == 1
    assert report["leg"]["trend"][0]["review_status"] == "unreviewed"
    assert report["leg"]["trend"][0]["measurement_type"] == "photographic_proxy"
    assert report["scalp"]["trend"] == []
    assert report["scalp"]["trend_unavailable_reason"] == "manual_review_required"
    assert report["scalp"]["records"][0]["scalp_candidate_fraction_percent"] is None
    assert report["complete"] is True
    assert json.loads((output / "progress.json").read_text())["status"] == "succeeded"
    assert str(tmp_path) not in report_path.read_text(encoding="utf-8")

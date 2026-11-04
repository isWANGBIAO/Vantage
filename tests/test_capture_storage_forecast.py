"""Synthetic capture events: no camera, disk scan, network, or private images."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.services.capture_storage_forecast import CaptureStorageForecast


@pytest.fixture
def rig(tmp_path):
    clock = [0.0]
    files = {}
    roots = [tmp_path / "photos", tmp_path / "screenshots"]
    for root in roots:
        root.mkdir()

    def stat(path):
        path = CaptureStorageForecast._path(path)
        if path in files:
            size, device = files[path]
            return SimpleNamespace(st_size=size, st_dev=device)
        if path in [CaptureStorageForecast._path(root) for root in roots]:
            return SimpleNamespace(st_dev=1)
        raise FileNotFoundError("synthetic missing file")

    def usage(_root):
        return SimpleNamespace(free=86400 * 100)

    service = CaptureStorageForecast(clock=lambda: clock[0], stat=stat, disk_usage=usage)

    def save(t, name, size=600, *, root=0, device=1):
        clock[0] = t
        path = roots[root] / name
        files[CaptureStorageForecast._path(path)] = (size, device)
        service.record_file(path)
        return path

    return SimpleNamespace(clock=clock, files=files, roots=roots, service=service, save=save, stat=stat)


def test_three_observed_capture_batches_use_real_elapsed_time_not_fixed_interval(rig):
    for t in [0, 60, 120]:
        rig.save(t, f"{t}.jpg")
    result = rig.service.snapshot(rig.roots, 60)
    assert result == {
        "status": "ready", "days_remaining": 10,
        "bytes_per_second": 10, "sample_count": 3,
        "observation_seconds": 120, "average_capture_bytes": 600,
    }


def test_custom_slow_capture_frequency_changes_estimate(rig):
    for t in [0, 300, 600]:
        rig.save(t, f"{t}.jpg")
    result = rig.service.snapshot(rig.roots, 300)
    assert result["status"] == "ready"
    assert result["bytes_per_second"] == 2
    assert result["days_remaining"] == 50


def test_skipped_capture_uses_actual_elapsed_time_not_nominal_sixty_seconds(rig):
    for t in [0, 120, 240]:
        rig.save(t, f"{t}.jpg")
    result = rig.service.snapshot(rig.roots, 60)
    assert result["status"] == "ready"
    assert result["bytes_per_second"] == 5
    assert result["days_remaining"] == 20


def test_all_monitors_and_photo_are_counted_without_tripling_sample_count(rig):
    for t in [0, 60, 120]:
        rig.save(t, f"photo{t}.jpg", 600)
        rig.save(t + 0.1, f"monitor1-{t}.jpg", 1200, root=1)
        rig.save(t + 0.2, f"monitor2-{t}.jpg", 1800, root=1)
    result = rig.service.snapshot(rig.roots, 60)
    assert result["sample_count"] == 3
    assert result["average_capture_bytes"] == 3600
    assert result["bytes_per_second"] == 60
    assert result["days_remaining"] == pytest.approx(100 / 60)


@pytest.mark.parametrize("count,step", [(0, 60), (1, 60), (2, 120), (3, 30), (10, 0.1)])
def test_initial_or_short_observation_does_not_claim_zero_days(rig, count, step):
    for n in range(count):
        rig.save(n * step, f"file{n}.jpg")
    result = rig.service.snapshot(rig.roots, 60)
    assert result["status"] == "insufficient_data"
    assert result["days_remaining"] is None
    assert result["bytes_per_second"] is None


def test_old_samples_expire_and_latest_only_does_not_claim_infinite_days(rig):
    for t in [0, 60, 120]:
        rig.save(t, f"{t}.jpg")
    rig.clock[0] = 301
    assert rig.service.snapshot(rig.roots, 60)["status"] == "insufficient_data"
    rig.save(2000, "after-idle.jpg")
    assert rig.service.snapshot(rig.roots, 60)["sample_count"] == 1
    assert rig.service.snapshot(rig.roots, 60)["days_remaining"] is None


def test_duplicate_or_overwritten_file_is_not_counted_as_new_storage(rig):
    rig.save(0, "same.jpg", 600)
    rig.save(60, "same.jpg", 600)
    rig.save(120, "same.jpg", 600)
    assert rig.service.snapshot(rig.roots, 60)["status"] == "insufficient_data"
    rig.save(180, "same.jpg", 1200)
    rig.save(240, "same.jpg", 1800)
    result = rig.service.snapshot(rig.roots, 60)
    assert result["status"] == "ready"
    assert result["bytes_per_second"] == 5


def test_unrelated_directory_images_are_not_part_of_forecast(rig, tmp_path):
    outside = tmp_path / "unrelated"
    for t in [0, 60, 120]:
        rig.clock[0] = t
        path = outside / f"{t}.jpg"
        rig.files[CaptureStorageForecast._path(path)] = (100000, 1)
        rig.service.record_file(path)
        rig.save(t, f"{t}.jpg", 600)
    assert rig.service.snapshot(rig.roots, 60)["bytes_per_second"] == 10


def test_multiple_volumes_choose_first_full_not_aggregate_free_space(rig):
    first_root, second_root = [CaptureStorageForecast._path(root) for root in rig.roots]

    def stat(path):
        path = CaptureStorageForecast._path(path)
        if path == second_root:
            return SimpleNamespace(st_dev=2)
        return rig.stat(path)

    rig.service._stat = stat
    rig.service._disk_usage = lambda root: SimpleNamespace(free=86400 * (100 if root == first_root else 20))
    for t in [0, 60, 120]:
        rig.save(t, f"p{t}.jpg", 600)
        rig.save(t, f"s{t}.jpg", 1200, root=1, device=2)
    result = rig.service.snapshot(rig.roots, 60)
    assert result["status"] == "ready"
    assert result["days_remaining"] == 1
    assert result["bytes_per_second"] == 30


def test_other_volume_without_observations_prevents_optimistic_forecast(rig):
    second_root = CaptureStorageForecast._path(rig.roots[1])
    rig.service._stat = lambda path: SimpleNamespace(st_dev=2) if CaptureStorageForecast._path(path) == second_root else rig.stat(path)
    for t in [0, 60, 120]:
        rig.save(t, f"p{t}.jpg")
    assert rig.service.snapshot(rig.roots, 60)["days_remaining"] is None


@pytest.mark.parametrize("bad_interval", [0, -1, None, True, float("nan"), float("inf")])
def test_invalid_capture_configuration_is_insufficient(rig, bad_interval):
    assert rig.service.snapshot(rig.roots, bad_interval)["status"] == "insufficient_data"


@pytest.mark.parametrize("bad_free", [-1, None, True, float("nan"), float("inf")])
def test_invalid_free_space_is_insufficient(rig, bad_free):
    rig.service._disk_usage = lambda _root: SimpleNamespace(free=bad_free)
    assert rig.service.snapshot(rig.roots, 60)["days_remaining"] is None


def test_true_full_disk_may_report_zero_with_valid_rate(rig):
    rig.service._disk_usage = lambda _root: SimpleNamespace(free=0)
    for t in [0, 60, 120]:
        rig.save(t, f"{t}.jpg")
    result = rig.service.snapshot(rig.roots, 60)
    assert result["status"] == "ready"
    assert result["days_remaining"] == 0


def test_unrepresentable_forecast_degrades_instead_of_emitting_infinity(rig):
    rig.service._disk_usage = lambda _root: SimpleNamespace(free=1e308)
    for t in [0, 60, 120]:
        rig.save(t, f"{t}.jpg", 1)
    assert rig.service.snapshot(rig.roots, 60)["days_remaining"] is None


def test_huge_integer_stat_is_rejected_without_overflow(rig):
    rig.save(0, "impossible.jpg", 10**10000)
    assert rig.service.snapshot(rig.roots, 60)["status"] == "insufficient_data"


def test_changed_roots_invalidate_existing_projection(rig):
    for t in [0, 60, 120]:
        rig.save(t, f"{t}.jpg")
    assert rig.service.snapshot(rig.roots, 60)["status"] == "ready"
    assert rig.service.snapshot([rig.roots[1]], 60)["status"] == "insufficient_data"


def test_clock_rollback_or_exception_requires_new_samples(rig):
    for t in [0, 60, 120]:
        rig.save(t, f"{t}.jpg")
    rig.clock[0] = 10
    assert rig.service.snapshot(rig.roots, 60)["sample_count"] == 0
    rig.service._clock = lambda: (_ for _ in ()).throw(RuntimeError("clock unavailable"))
    rig.service.record_file(rig.roots[0] / "anything.jpg")
    assert rig.service.snapshot(rig.roots, 60)["status"] == "insufficient_data"


def test_stat_failure_resets_existing_observations_without_breaking_capture(rig):
    for t in [0, 60, 120]:
        rig.save(t, f"{t}.jpg")
    rig.service.record_file(rig.roots[0] / "missing.jpg")
    assert rig.service.snapshot(rig.roots, 60)["status"] == "insufficient_data"


def test_bounded_history_never_projects_from_silently_dropped_writes(rig):
    rig.service._max_events = 3
    for n in range(4):
        rig.save(n * 60, f"{n}.jpg")
    assert len(rig.service._events) <= 3
    assert len(rig.service._sizes) <= 3
    assert rig.service.snapshot(rig.roots, 60)["status"] == "insufficient_data"


def test_parallel_workers_are_counted_once_and_payload_has_no_paths(rig):
    for t in [0, 60, 120]:
        rig.clock[0] = t
        paths = [rig.roots[0] / f"{t}-{n}.jpg" for n in range(8)]
        for path in paths:
            rig.files[CaptureStorageForecast._path(path)] = (600, 1)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(rig.service.record_file, paths + paths))
    result = rig.service.snapshot(rig.roots, 60)
    assert result["bytes_per_second"] == 80
    assert str(rig.roots[0]) not in str(result)


@pytest.mark.parametrize("gps", [False, True])
def test_real_image_save_records_final_file_size_even_when_exif_fails(monkeypatch, tmp_path, gps):
    from src.manager import get_location

    observed = []
    recorder = SimpleNamespace(record_file=lambda path: observed.append((path, path.stat().st_size)))
    monkeypatch.setattr(get_location, "capture_storage_forecast", recorder)
    monkeypatch.setattr(get_location.piexif, "dump", lambda *_: (_ for _ in ()).throw(ValueError("synthetic EXIF failure")))
    path = tmp_path / "图像.jpg"
    get_location.save_image_with_gps(path, np.zeros((8, 8, 3), dtype=np.uint8), 1 if gps else None, 2 if gps else None)
    assert observed == [(path, path.stat().st_size)]
    assert cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR) is not None


def test_failed_image_encoding_has_no_capture_event(monkeypatch, tmp_path):
    from src.manager import get_location

    observed = []
    monkeypatch.setattr(get_location, "capture_storage_forecast", SimpleNamespace(record_file=observed.append))
    monkeypatch.setattr(get_location.cv2, "imencode", lambda *_: (False, None))
    with pytest.raises(OSError):
        get_location.save_image_with_gps(tmp_path / "bad.jpg", np.zeros((8, 8, 3), dtype=np.uint8), None, None)
    assert observed == []


@pytest.mark.parametrize("gps", [False, True])
def test_statistical_recorder_exception_never_prevents_real_image_save(monkeypatch, tmp_path, gps):
    from src.manager import get_location

    def fail_record(_path):
        raise RuntimeError("synthetic recorder failure")

    monkeypatch.setattr(get_location, "capture_storage_forecast", SimpleNamespace(record_file=fail_record))
    path = tmp_path / "still-saved.jpg"
    get_location.save_image_with_gps(path, np.zeros((8, 8, 3), dtype=np.uint8), 1 if gps else None, 2 if gps else None)
    assert path.stat().st_size > 0
    assert cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR) is not None

import importlib
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def _scanner_type():
    module = importlib.import_module("src.services.directory_size_scanner")
    return module.DirectorySizeScanner


def test_one_entry_steps_advance_without_rescanning_and_finish_exactly(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    first = tmp_path / "a.bin"
    second = nested / "b.bin"
    first.write_bytes(b"a")
    second.write_bytes(b"bc")
    size_calls = []

    def getsize(path):
        size_calls.append(Path(path))
        return os.path.getsize(path)

    scanner = _scanner_type()(
        tmp_path,
        max_entries_per_step=1,
        max_seconds_per_step=None,
        getsize_fn=getsize,
    )

    snapshots = [scanner.step(), scanner.step(), scanner.step()]

    assert [snapshot.total_size for snapshot in snapshots] == [1, 1, 3]
    assert [snapshot.complete for snapshot in snapshots] == [False, False, True]
    assert [snapshot.entries_processed for snapshot in snapshots] == [1, 1, 1]
    assert size_calls == [first, second]


def test_completed_scan_is_cached_without_io_until_refresh_deadline(tmp_path):
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"payload")
    now = [0.0]
    io_counts = {"scandir": 0, "getsize": 0}

    def scandir(path):
        io_counts["scandir"] += 1
        return os.scandir(path)

    def getsize(path):
        io_counts["getsize"] += 1
        return os.path.getsize(path)

    scanner = _scanner_type()(
        tmp_path,
        max_entries_per_step=10,
        max_seconds_per_step=None,
        refresh_interval_seconds=15 * 60,
        monotonic_clock=lambda: now[0],
        scandir_fn=scandir,
        getsize_fn=getsize,
    )

    first = scanner.step()
    first_counts = dict(io_counts)
    now[0] = 899.999
    cached = scanner.step()

    assert first.complete is True
    assert cached.complete is True
    assert cached.total_size == first.total_size
    assert cached.skipped_entries == first.skipped_entries
    assert cached.entries_processed == 0
    assert io_counts == first_counts

    now[0] = 900.0
    payload.write_bytes(b"refreshed")
    refreshed = scanner.step()

    assert refreshed.complete is True
    assert refreshed.total_size == len(b"refreshed")
    assert io_counts["scandir"] > first_counts["scandir"]
    assert io_counts["getsize"] > first_counts["getsize"]


def test_disappearing_file_is_skipped_without_losing_other_sizes(tmp_path):
    good = tmp_path / "a-good.bin"
    missing = tmp_path / "b-missing.bin"
    good.write_bytes(b"abc")
    missing.write_bytes(b"12345")

    def getsize(path):
        if Path(path) == missing:
            raise OSError("file disappeared")
        return os.path.getsize(path)

    scanner = _scanner_type()(
        tmp_path,
        max_entries_per_step=10,
        max_seconds_per_step=None,
        getsize_fn=getsize,
    )

    result = scanner.step()

    assert result.complete is True
    assert result.total_size == 3
    assert result.skipped_entries == 1


def test_scanner_stays_inside_root_and_does_not_follow_directory_symlinks(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    inside_file = root / "inside.bin"
    outside_file = outside / "outside.bin"
    inside_file.write_bytes(b"in")
    outside_file.write_bytes(b"outside")
    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    size_calls = []

    def getsize(path):
        size_calls.append(Path(path))
        return os.path.getsize(path)

    scanner = _scanner_type()(
        root,
        max_entries_per_step=10,
        max_seconds_per_step=None,
        getsize_fn=getsize,
    )

    result = scanner.step()

    assert result.complete is True
    assert result.total_size == 2
    assert size_calls == [inside_file]
    assert outside_file not in size_calls


def test_time_budget_stops_before_processing_entry_loaded_after_deadline(tmp_path):
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"data")
    now = [0.0]

    def scandir(path):
        entries = list(os.scandir(path))
        now[0] = 1.0
        return entries

    scanner = _scanner_type()(
        tmp_path,
        max_entries_per_step=10,
        max_seconds_per_step=0.5,
        monotonic_clock=lambda: now[0],
        scandir_fn=scandir,
    )

    partial = scanner.step()
    complete = scanner.step()

    assert partial.complete is False
    assert partial.entries_processed == 0
    assert partial.total_size == 0
    assert complete.complete is True
    assert complete.total_size == 4


def test_time_budget_stops_while_draining_empty_directories(tmp_path):
    for name in ("a", "b", "c"):
        (tmp_path / name).mkdir()
    now = [0.0]

    def scandir(path):
        entries = list(os.scandir(path))
        if Path(path) != tmp_path:
            now[0] += 1.0
        return entries

    scanner = _scanner_type()(
        tmp_path,
        max_entries_per_step=10,
        max_seconds_per_step=1.5,
        monotonic_clock=lambda: now[0],
        scandir_fn=scandir,
    )

    partial = scanner.step()
    complete = scanner.step()

    assert partial.complete is False
    assert complete.complete is True


def test_entries_are_processed_in_deterministic_name_order(tmp_path):
    files = [tmp_path / name for name in ("z.bin", "b.bin", "a.bin")]
    for file_path in files:
        file_path.write_bytes(b"x")
    processed = []

    def getsize(path):
        processed.append(Path(path).name)
        return os.path.getsize(path)

    scanner = _scanner_type()(
        tmp_path,
        max_entries_per_step=10,
        max_seconds_per_step=None,
        getsize_fn=getsize,
    )

    assert scanner.step().complete is True
    assert processed == ["a.bin", "b.bin", "z.bin"]


def test_concurrent_steps_do_not_double_count_entries(tmp_path):
    expected_size = 0
    for index in range(20):
        payload = bytes([index]) * (index + 1)
        (tmp_path / f"{index:02d}.bin").write_bytes(payload)
        expected_size += len(payload)
    scanner = _scanner_type()(
        tmp_path,
        max_entries_per_step=1,
        max_seconds_per_step=None,
    )

    def drain_scanner(_worker):
        for _ in range(30):
            result = scanner.step()
            if result.complete:
                return result
        return result

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(drain_scanner, range(4)))

    assert any(result.complete for result in results)
    assert scanner.step().total_size == expected_size


def test_queued_directory_that_disappears_is_skipped(tmp_path):
    vanishing = tmp_path / "vanishing"
    vanishing.mkdir()
    (vanishing / "payload.bin").write_bytes(b"payload")
    scanner = _scanner_type()(
        tmp_path,
        max_entries_per_step=1,
        max_seconds_per_step=None,
    )

    queued = scanner.step()
    shutil.rmtree(vanishing)
    finished = scanner.step()

    assert queued.complete is False
    assert finished.complete is True
    assert finished.total_size == 0
    assert finished.skipped_entries == 1

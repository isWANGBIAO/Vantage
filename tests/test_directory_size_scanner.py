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
    scandir_calls = []

    def scandir(path):
        directory = Path(path)
        scandir_calls.append(directory)
        with os.scandir(directory) as iterator:
            entries = {entry.name: entry for entry in iterator}
        order = ["a.bin", "nested"] if directory == tmp_path else ["b.bin"]
        return iter(entries[name] for name in order)

    def getsize(path):
        size_calls.append(Path(path))
        return os.path.getsize(path)

    scanner = _scanner_type()(
        tmp_path,
        max_entries_per_step=1,
        max_seconds_per_step=None,
        scandir_fn=scandir,
        getsize_fn=getsize,
    )

    snapshots = [scanner.step(), scanner.step(), scanner.step(), scanner.step()]

    assert [snapshot.total_size for snapshot in snapshots] == [1, 1, 3, 3]
    assert [snapshot.complete for snapshot in snapshots] == [False, False, False, True]
    assert [snapshot.entries_processed for snapshot in snapshots] == [1, 1, 1, 0]
    assert size_calls == [first, second]
    assert scandir_calls == [tmp_path, nested]


def test_slow_scandir_iterator_is_resumed_without_consuming_whole_directory(tmp_path):
    for index in range(40):
        (tmp_path / f"{index:02d}.bin").write_bytes(b"x")
    with os.scandir(tmp_path) as directory_iterator:
        entries = list(directory_iterator)
    entries.sort(key=lambda entry: entry.name)
    now = [0.0]
    scandir_calls = []

    class SlowIterator:
        def __init__(self, values):
            self._values = iter(values)
            self.yielded = 0
            self.closed = False

        def __iter__(self):
            return self

        def __next__(self):
            value = next(self._values)
            now[0] += 0.020
            self.yielded += 1
            return value

        def close(self):
            self.closed = True

    slow_iterator = SlowIterator(entries)

    def scandir(path):
        scandir_calls.append(Path(path))
        return slow_iterator

    scanner = _scanner_type()(
        tmp_path,
        max_entries_per_step=100,
        max_seconds_per_step=0.050,
        monotonic_clock=lambda: now[0],
        scandir_fn=scandir,
    )

    snapshots = [scanner.step()]

    assert 0 < slow_iterator.yielded < len(entries)
    assert snapshots[0].entries_processed == slow_iterator.yielded
    assert snapshots[0].complete is False

    for _ in range(len(entries) + 1):
        if snapshots[-1].complete:
            break
        snapshots.append(scanner.step())
    else:
        pytest.fail("scanner did not finish after enough bounded steps")

    assert snapshots[-1].total_size == len(entries)
    assert [snapshot.total_size for snapshot in snapshots] == sorted(
        snapshot.total_size for snapshot in snapshots
    )
    assert scandir_calls == [tmp_path]
    assert slow_iterator.closed is True


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


def test_missing_root_is_retryable_instead_of_caching_exact_zero(tmp_path):
    root = tmp_path / "appears-later"
    now = [0.0]
    scanner = _scanner_type()(
        root,
        max_entries_per_step=10,
        max_seconds_per_step=None,
        monotonic_clock=lambda: now[0],
    )

    missing = scanner.step()

    assert missing.complete is False
    assert missing.total_size == 0

    root.mkdir()
    (root / "payload.bin").write_bytes(b"1234567")
    now[0] = 60.0
    recovered = scanner.step()

    assert recovered.complete is True
    assert recovered.total_size == 7


def test_root_permission_failure_is_retryable_on_the_next_step(tmp_path):
    root = tmp_path / "restricted"
    root.mkdir()
    (root / "payload.bin").write_bytes(b"1234567")
    now = [0.0]
    attempts = []

    def scandir(path):
        attempts.append(Path(path))
        if len(attempts) == 1:
            raise PermissionError("temporarily unavailable")
        return os.scandir(path)

    scanner = _scanner_type()(
        root,
        max_entries_per_step=10,
        max_seconds_per_step=None,
        monotonic_clock=lambda: now[0],
        scandir_fn=scandir,
    )

    denied = scanner.step()
    now[0] = 60.0
    recovered = scanner.step()

    assert denied.complete is False
    assert denied.total_size == 0
    assert recovered.complete is True
    assert recovered.total_size == 7
    assert attempts == [root, root]


def test_root_iterator_error_closes_and_retries_without_double_counting(tmp_path):
    root = tmp_path / "interrupted"
    root.mkdir()
    first = root / "a.bin"
    second = root / "b.bin"
    first.write_bytes(b"aa")
    second.write_bytes(b"bbb")
    with os.scandir(root) as directory_iterator:
        entries = {entry.name: entry for entry in directory_iterator}
    attempts = []

    class FailingIterator:
        def __init__(self):
            self._returned_first = False
            self.closed = False

        def __iter__(self):
            return self

        def __next__(self):
            if not self._returned_first:
                self._returned_first = True
                return entries["a.bin"]
            raise PermissionError("iteration interrupted")

        def close(self):
            self.closed = True

    failing_iterator = FailingIterator()

    def scandir(path):
        attempts.append(Path(path))
        if len(attempts) == 1:
            return failing_iterator
        return iter((entries["a.bin"], entries["b.bin"]))

    scanner = _scanner_type()(
        root,
        max_entries_per_step=10,
        max_seconds_per_step=None,
        scandir_fn=scandir,
    )

    interrupted = scanner.step()
    recovered = scanner.step()

    assert interrupted.complete is False
    assert interrupted.total_size == 2
    assert failing_iterator.closed is True
    assert recovered.complete is True
    assert recovered.total_size == 5
    assert attempts == [root, root]


def test_successful_empty_root_is_exact_zero_and_cached_without_io(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    now = [0.0]
    scandir_calls = []

    def scandir(path):
        scandir_calls.append(Path(path))
        return os.scandir(path)

    scanner = _scanner_type()(
        root,
        max_entries_per_step=10,
        max_seconds_per_step=None,
        monotonic_clock=lambda: now[0],
        scandir_fn=scandir,
    )

    exact = scanner.step()
    now[0] = 899.0
    cached = scanner.step()

    assert exact.complete is True
    assert exact.total_size == 0
    assert cached.complete is True
    assert cached.total_size == 0
    assert scandir_calls == [root]


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


def test_injected_directory_order_is_stable_without_rescanning(tmp_path):
    files = [tmp_path / name for name in ("z.bin", "b.bin", "a.bin")]
    for file_path in files:
        file_path.write_bytes(b"x")
    processed = []
    scandir_calls = []

    def scandir(path):
        scandir_calls.append(Path(path))
        with os.scandir(path) as iterator:
            entries = {entry.name: entry for entry in iterator}
        return iter(entries[name] for name in ("z.bin", "b.bin", "a.bin"))

    def getsize(path):
        processed.append(Path(path).name)
        return os.path.getsize(path)

    scanner = _scanner_type()(
        tmp_path,
        max_entries_per_step=10,
        max_seconds_per_step=None,
        scandir_fn=scandir,
        getsize_fn=getsize,
    )

    assert scanner.step().complete is True
    assert processed == ["z.bin", "b.bin", "a.bin"]
    assert scandir_calls == [tmp_path]


def test_close_releases_a_partially_consumed_directory_iterator(tmp_path):
    for name in ("a.bin", "b.bin"):
        (tmp_path / name).write_bytes(b"x")
    with os.scandir(tmp_path) as directory_iterator:
        entries = list(directory_iterator)

    class CloseTrackingIterator:
        def __init__(self, values):
            self._values = iter(values)
            self.closed = False

        def __iter__(self):
            return self

        def __next__(self):
            return next(self._values)

        def close(self):
            self.closed = True

    iterator = CloseTrackingIterator(entries)
    scanner = _scanner_type()(
        tmp_path,
        max_entries_per_step=1,
        max_seconds_per_step=None,
        scandir_fn=lambda _path: iterator,
    )

    assert scanner.step().complete is False
    assert iterator.closed is False

    scanner.close()

    assert iterator.closed is True


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

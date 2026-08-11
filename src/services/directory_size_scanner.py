from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DirectorySizeScanSnapshot:
    total_size: int
    complete: bool
    entries_processed: int
    skipped_entries: int


class DirectorySizeScanner:
    def __init__(
        self,
        root,
        *,
        max_entries_per_step=20_000,
        max_seconds_per_step=3.0,
        refresh_interval_seconds=15 * 60,
        monotonic_clock=time.monotonic,
        scandir_fn=os.scandir,
        getsize_fn=os.path.getsize,
    ):
        self.root = Path(root).resolve(strict=False)
        self.max_entries_per_step = max_entries_per_step
        self.max_seconds_per_step = max_seconds_per_step
        self.refresh_interval_seconds = refresh_interval_seconds
        self._monotonic_clock = monotonic_clock
        self._scandir_fn = scandir_fn
        self._getsize_fn = getsize_fn
        self._lock = threading.RLock()
        self._reset_scan_locked()

    def _reset_scan_locked(self):
        self._pending_directories = deque([self.root])
        self._current_entries = deque()
        self._visited_directories = set()
        self._total_size = 0
        self._skipped_entries = 0
        self._complete = False
        self._completed_at = None

    def _snapshot_locked(self, entries_processed):
        return DirectorySizeScanSnapshot(
            total_size=self._total_size,
            complete=self._complete,
            entries_processed=entries_processed,
            skipped_entries=self._skipped_entries,
        )

    def _resolved_path_within_root(self, path):
        try:
            Path(os.path.realpath(path)).relative_to(self.root)
            return True
        except (OSError, ValueError):
            return False

    def _load_next_directory_locked(self, started_at):
        while self._pending_directories:
            if self._time_budget_reached_locked(started_at):
                return False
            directory = self._pending_directories.popleft()
            if not self._resolved_path_within_root(directory):
                self._skipped_entries += 1
                continue

            resolved_directory = Path(os.path.realpath(directory))
            directory_key = os.path.normcase(os.fspath(resolved_directory))
            if directory_key in self._visited_directories:
                continue
            if directory != self.root and os.path.islink(directory):
                continue
            self._visited_directories.add(directory_key)

            iterator = None
            try:
                iterator = self._scandir_fn(directory)
                entries = list(iterator)
            except OSError:
                self._skipped_entries += 1
                continue
            finally:
                close = getattr(iterator, "close", None)
                if callable(close):
                    close()

            entries.sort(key=lambda entry: (os.path.normcase(entry.name), entry.name))
            self._current_entries.extend(entries)
            if self._current_entries:
                return True
        return False

    def _next_entry_locked(self, started_at):
        while not self._current_entries:
            if not self._load_next_directory_locked(started_at):
                return None
        return self._current_entries.popleft()

    def _process_entry_locked(self, entry):
        entry_path = Path(entry.path)
        if not self._resolved_path_within_root(entry_path):
            self._skipped_entries += 1
            return

        try:
            if entry.is_symlink():
                return
            if entry.is_dir(follow_symlinks=False):
                self._pending_directories.append(entry_path)
                return
            if entry.is_file(follow_symlinks=False):
                file_size = self._getsize_fn(entry_path)
                if isinstance(file_size, bool) or not math.isfinite(file_size):
                    raise OSError("invalid file size")
                self._total_size += max(0, int(file_size))
        except OSError:
            self._skipped_entries += 1

    def _time_budget_reached_locked(self, started_at):
        if self.max_seconds_per_step is None:
            return False
        return self._monotonic_clock() - started_at >= self.max_seconds_per_step

    def step(self):
        with self._lock:
            now = self._monotonic_clock()
            if self._complete:
                cache_age = now - self._completed_at
                if 0 <= cache_age < self.refresh_interval_seconds:
                    return self._snapshot_locked(entries_processed=0)
                self._reset_scan_locked()

            started_at = now
            entries_processed = 0
            while True:
                if (
                    self.max_entries_per_step is not None
                    and entries_processed >= self.max_entries_per_step
                ):
                    break
                if self._time_budget_reached_locked(started_at):
                    break

                entry = self._next_entry_locked(started_at)
                if entry is None:
                    break
                if self._time_budget_reached_locked(started_at):
                    self._current_entries.appendleft(entry)
                    break

                entries_processed += 1
                self._process_entry_locked(entry)

            if not self._current_entries and not self._pending_directories:
                self._complete = True
                self._completed_at = self._monotonic_clock()

            return self._snapshot_locked(entries_processed)

from __future__ import annotations

import math
import os
import stat
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
        self._configured_root = Path(os.path.abspath(os.fspath(root)))
        self.max_entries_per_step = max_entries_per_step
        self.max_seconds_per_step = max_seconds_per_step
        self.refresh_interval_seconds = refresh_interval_seconds
        self._monotonic_clock = monotonic_clock
        self._scandir_fn = scandir_fn
        self._getsize_fn = getsize_fn
        self._lock = threading.RLock()
        self._current_iterator = None
        self._current_iterator_owner = None
        self._current_directory = None
        self._current_directory_key = None
        self._closed = False
        resolved_root, root_identity = self._configured_root_state_locked()
        self._reset_scan_locked(
            resolved_root=resolved_root,
            root_identity=root_identity,
        )

    def _configured_root_state_locked(self):
        resolved_root = Path(os.path.realpath(self._configured_root))
        try:
            root_stat = os.stat(self._configured_root, follow_symlinks=True)
        except OSError:
            return resolved_root, None
        if not stat.S_ISDIR(root_stat.st_mode):
            return resolved_root, None
        return resolved_root, (
            int(root_stat.st_dev),
            int(root_stat.st_ino),
            int(stat.S_IFMT(root_stat.st_mode)),
            int(getattr(root_stat, "st_file_attributes", 0)),
        )

    def _refresh_configured_root_locked(self):
        resolved_root, root_identity = self._configured_root_state_locked()
        root_changed = (
            os.path.normcase(os.path.abspath(os.fspath(resolved_root)))
            != os.path.normcase(os.path.abspath(os.fspath(self.root)))
            or root_identity != self._root_identity
        )
        if root_changed:
            self._reset_scan_locked(
                resolved_root=resolved_root,
                root_identity=root_identity,
            )
            return False
        return True

    def _close_current_iterator_locked(self):
        iterator = self._current_iterator
        owner = self._current_iterator_owner
        self._current_iterator = None
        self._current_iterator_owner = None
        self._current_directory = None
        self._current_directory_key = None

        closed_resources = set()
        for resource in (iterator, owner):
            if resource is None or id(resource) in closed_resources:
                continue
            closed_resources.add(id(resource))
            close = getattr(resource, "close", None)
            if callable(close):
                try:
                    close()
                except OSError:
                    pass

    def _reset_scan_locked(self, *, resolved_root=None, root_identity=None):
        self._close_current_iterator_locked()
        if resolved_root is not None:
            self.root = Path(resolved_root)
            self._root_identity = root_identity
        self._pending_directories = deque([self.root])
        self._visited_directories = set()
        self._processed_entries = set()
        self._total_size = 0
        self._skipped_entries = 0
        self._complete = False
        self._completed_at = None

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._close_current_iterator_locked()
            self._pending_directories.clear()

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

    def _open_next_directory_locked(self, started_at):
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

            owner = None
            try:
                owner = self._scandir_fn(directory)
                iterator = iter(owner)
            except OSError:
                close = getattr(owner, "close", None)
                if callable(close):
                    close()
                if directory == self.root:
                    self._pending_directories.appendleft(self.root)
                    return False
                self._skipped_entries += 1
                continue

            self._visited_directories.add(directory_key)
            self._current_iterator = iterator
            self._current_iterator_owner = owner
            self._current_directory = directory
            self._current_directory_key = directory_key
            return True
        return False

    def _next_entry_locked(self, started_at):
        while True:
            if self._time_budget_reached_locked(started_at):
                return None
            if self._current_iterator is None:
                if not self._open_next_directory_locked(started_at):
                    return None
                if self._time_budget_reached_locked(started_at):
                    return None

            try:
                return next(self._current_iterator)
            except StopIteration:
                self._close_current_iterator_locked()
            except OSError:
                failed_directory = self._current_directory
                failed_directory_key = self._current_directory_key
                self._close_current_iterator_locked()
                if failed_directory == self.root:
                    self._visited_directories.discard(failed_directory_key)
                    self._pending_directories.appendleft(self.root)
                    return None
                self._skipped_entries += 1

    def _process_entry_locked(self, entry):
        entry_path = Path(entry.path)
        entry_key = os.path.normcase(os.path.abspath(os.fspath(entry_path)))
        if entry_key in self._processed_entries:
            return
        self._processed_entries.add(entry_key)

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
            if self._closed:
                raise RuntimeError("directory size scanner is closed")

            root_stable = self._refresh_configured_root_locked()
            now = self._monotonic_clock()
            if self._complete and root_stable:
                cache_age = now - self._completed_at
                if 0 <= cache_age < self.refresh_interval_seconds:
                    return self._snapshot_locked(entries_processed=0)
                self._reset_scan_locked()

            started_at = now
            entries_processed = 0
            while True:
                if not self._refresh_configured_root_locked():
                    entries_processed = 0
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

                entries_processed += 1
                self._process_entry_locked(entry)
                if not self._refresh_configured_root_locked():
                    entries_processed = 0

            if self._current_iterator is None and not self._pending_directories:
                if self._refresh_configured_root_locked():
                    self._complete = True
                    self._completed_at = self._monotonic_clock()

            return self._snapshot_locked(entries_processed)

"""Bounded, process-local forecasts from images actually saved by capture workers.

No historical directory scan, image content, or private state is persisted. A
forecast is a recent capture-rate projection, not a promise about disk lifetime.
"""

from __future__ import annotations

from collections import deque
import math
import os
from pathlib import Path
import shutil
import threading
import time


class CaptureStorageForecast:
    WINDOW_SECONDS = 30 * 60
    MIN_OBSERVATION_SECONDS = 120

    def __init__(self, *, clock=None, stat=None, disk_usage=None, max_events=10000):
        self._clock = clock or time.monotonic
        self._stat = stat or os.stat
        self._disk_usage = disk_usage or shutil.disk_usage
        self._max_events = max(3, int(max_events))
        self._events = deque()
        self._sizes = {}
        self._lock = threading.Lock()
        self._last_now = None
        self._roots = None
        self._unreliable_until = None

    @staticmethod
    def _number(value, *, positive=False):
        try:
            return (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and (value > 0 if positive else value >= 0)
            )
        except OverflowError:
            return False

    @staticmethod
    def _path(value):
        return os.path.normcase(os.path.realpath(os.fspath(value)))

    def _reset(self):
        self._events.clear()
        self._sizes.clear()
        self._unreliable_until = None

    def _advance(self):
        try:
            now = self._clock()
        except Exception:
            self._reset()
            self._last_now = None
            return None
        if not self._number(now):
            self._reset()
            self._last_now = None
            return None
        if self._last_now is not None and now < self._last_now:
            self._reset()
        self._last_now = now
        cutoff = now - self.WINDOW_SECONDS
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()
        # Keep only bounded, recent file identities, not an ever-growing log.
        self._sizes = {path: item for path, item in self._sizes.items() if item[0] >= cutoff}
        return now

    def record_file(self, path):
        """Observe a completed file save; diagnostic failure never breaks capture."""
        with self._lock:
            now = self._advance()
            if now is None:
                return
            try:
                normalized = self._path(path)
                info = self._stat(normalized)
                size, device = info.st_size, info.st_dev
                if not self._number(size, positive=True):
                    raise ValueError("invalid saved image size")
            except (OSError, ValueError, TypeError, AttributeError):
                # A missing write would bias the prediction towards too many days.
                self._reset()
                return
            previous = self._sizes.get(normalized)
            added = size if previous is None else max(0, size - previous[1])
            if previous is not None and previous[2] != device:
                self._reset()
                added = size
            if len(self._sizes) >= self._max_events and normalized not in self._sizes:
                self._reset()
                self._unreliable_until = now + self.WINDOW_SECONDS
            self._sizes[normalized] = (now, size, device)
            if added == 0:
                return
            if len(self._events) >= self._max_events:
                self._events.popleft()
                self._unreliable_until = now + self.WINDOW_SECONDS
            self._events.append((now, normalized, device, added))

    @staticmethod
    def _unavailable(sample_count=0, observation_seconds=0):
        return {
            "status": "insufficient_data",
            "days_remaining": None,
            "bytes_per_second": None,
            "sample_count": sample_count,
            "observation_seconds": observation_seconds,
            "average_capture_bytes": None,
        }

    @staticmethod
    def _batches(events, gap):
        batches = []
        for timestamp, _path, _device, size in events:
            if not batches or timestamp - batches[-1][0] > gap:
                batches.append([timestamp, size])
            else:
                batches[-1][1] += size
        return batches

    def snapshot(self, roots, capture_interval_seconds):
        """Return the first-to-fill volume estimate, without exposing any paths.

        Samples before the first time batch form the baseline. Subsequent bytes
        divided by observed elapsed time include real skipped/slow captures.
        """
        with self._lock:
            now = self._advance()
            if now is None or not self._number(capture_interval_seconds, positive=True):
                return self._unavailable()
            try:
                normalized_roots = tuple(sorted({self._path(root) for root in roots if root}))
                if not normalized_roots:
                    return self._unavailable()
                if self._roots is not None and normalized_roots != self._roots:
                    self._reset()
                self._roots = normalized_roots
                volumes = {}
                for root in normalized_roots:
                    device = self._stat(root).st_dev
                    free = self._disk_usage(root).free
                    if not self._number(free):
                        return self._unavailable()
                    volumes[device] = min(volumes.get(device, free), free)
            except (OSError, ValueError, TypeError, AttributeError):
                return self._unavailable()
            if self._unreliable_until is not None and now < self._unreliable_until:
                return self._unavailable()

            events = [event for event in self._events if any(
                Path(event[1]).is_relative_to(root) for root in normalized_roots
            )]
            gap = max(1.0, min(15.0, capture_interval_seconds / 2))
            all_batches = self._batches(events, gap)
            span = all_batches[-1][0] - all_batches[0][0] if all_batches else 0
            count = len(all_batches)
            unavailable = self._unavailable(count, span)
            if count < 3 or span < self.MIN_OBSERVATION_SECONDS:
                return unavailable
            rates = []
            days = []
            for device, free in volumes.items():
                batches = self._batches([event for event in events if event[2] == device], gap)
                if len(batches) < 3:
                    return unavailable
                elapsed = batches[-1][0] - batches[0][0]
                if elapsed < self.MIN_OBSERVATION_SECONDS or now - batches[-1][0] > max(180, 3 * capture_interval_seconds):
                    return unavailable
                rate = sum(float(batch[1]) for batch in batches[1:]) / elapsed
                if not self._number(rate, positive=True):
                    return unavailable
                days_remaining = free / rate / 86400
                if not self._number(days_remaining):
                    return unavailable
                rates.append(rate)
                days.append(days_remaining)
            total_rate = sum(rates)
            average_bytes = sum(float(batch[1]) for batch in all_batches) / count
            if not self._number(total_rate, positive=True) or not self._number(average_bytes, positive=True):
                return unavailable
            return {
                "status": "ready",
                "days_remaining": min(days),
                "bytes_per_second": total_rate,
                "sample_count": count,
                "observation_seconds": span,
                "average_capture_bytes": average_bytes,
            }


capture_storage_forecast = CaptureStorageForecast()

from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import threading
import time
from typing import Iterator, Literal


BACKEND_RUNTIME_LOCK_NAME = ".vantage-backend-runtime.lock"
DEFAULT_BACKEND_RUNTIME_LOCK_TIMEOUT_SECONDS = 300.0
DEFAULT_BACKEND_RUNTIME_LOCK_POLL_SECONDS = 0.05
BACKEND_RUNTIME_LOCK_READER_SLOTS = 64

BackendRuntimeLockMode = Literal["exclusive", "shared"]

_thread_state = threading.local()


def backend_runtime_lock_path(project_root: str | Path) -> Path:
    return Path(project_root).resolve() / BACKEND_RUNTIME_LOCK_NAME


def _normalized_lock_path(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _locally_held_modes() -> dict[str, BackendRuntimeLockMode]:
    held_modes = getattr(_thread_state, "held_modes", None)
    if held_modes is None:
        held_modes = {}
        _thread_state.held_modes = held_modes
    return held_modes


def backend_runtime_lock_is_held(
    project_root: str | Path,
) -> bool:
    normalized = _normalized_lock_path(backend_runtime_lock_path(project_root))
    return normalized in _locally_held_modes()


class BackendRuntimeFileLock:
    def __init__(
        self,
        path: str | Path,
        *,
        mode: BackendRuntimeLockMode = "exclusive",
        timeout_seconds: float = DEFAULT_BACKEND_RUNTIME_LOCK_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_BACKEND_RUNTIME_LOCK_POLL_SECONDS,
        monotonic=time.monotonic,
        sleep=time.sleep,
    ) -> None:
        if timeout_seconds < 0:
            raise ValueError("backend runtime lock timeout must be non-negative")
        if poll_interval_seconds <= 0:
            raise ValueError("backend runtime lock poll interval must be positive")
        if mode not in ("exclusive", "shared"):
            raise ValueError("backend runtime lock mode must be exclusive or shared")
        self.path = Path(path)
        self.mode = mode
        self.timeout_seconds = float(timeout_seconds)
        self.poll_interval_seconds = float(poll_interval_seconds)
        self._monotonic = monotonic
        self._sleep = sleep
        self._handle = None
        self._reader_slot: int | None = None

    def _try_windows_lock_range(self, offset: int, length: int) -> bool:
        assert self._handle is not None
        import msvcrt

        try:
            self._handle.seek(offset)
            msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, length)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                return False
            raise
        return True

    def _unlock_windows_range(self, offset: int, length: int) -> None:
        assert self._handle is not None
        import msvcrt

        self._handle.seek(offset)
        msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, length)

    def _try_posix_flock(self) -> bool:
        assert self._handle is not None
        import fcntl

        operation = fcntl.LOCK_EX if self.mode == "exclusive" else fcntl.LOCK_SH
        try:
            fcntl.flock(
                self._handle.fileno(),
                operation | fcntl.LOCK_NB,
            )
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                return False
            raise
        return True

    def _try_lock(self) -> bool:
        if os.name != "nt":
            return self._try_posix_flock()

        total_bytes = BACKEND_RUNTIME_LOCK_READER_SLOTS + 1
        if self.mode == "exclusive":
            return self._try_windows_lock_range(0, total_bytes)

        if not self._try_windows_lock_range(0, 1):
            return False
        try:
            for slot in range(1, total_bytes):
                if self._try_windows_lock_range(slot, 1):
                    self._reader_slot = slot
                    return True
            return False
        finally:
            self._unlock_windows_range(0, 1)

    def acquire(self) -> None:
        if self._handle is not None:
            raise RuntimeError("backend runtime lock is already acquired")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            required_bytes = BACKEND_RUNTIME_LOCK_READER_SLOTS + 1
            handle.seek(0, os.SEEK_END)
            current_bytes = handle.tell()
            if current_bytes < required_bytes:
                handle.write(b"\0" * (required_bytes - current_bytes))
                handle.flush()
                os.fsync(handle.fileno())
            self._handle = handle
            deadline = self._monotonic() + self.timeout_seconds
            while True:
                if self._try_lock():
                    return
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"timed out waiting for backend runtime lock: {self.path}"
                    )
                self._sleep(min(self.poll_interval_seconds, remaining))
        except BaseException:
            self._handle = None
            handle.close()
            raise

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            self._handle = handle
            if os.name != "nt":
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif self.mode == "shared":
                if self._reader_slot is None:
                    raise RuntimeError("backend runtime shared lock has no reader slot")
                self._unlock_windows_range(self._reader_slot, 1)
                self._reader_slot = None
            else:
                self._unlock_windows_range(
                    0,
                    BACKEND_RUNTIME_LOCK_READER_SLOTS + 1,
                )
        finally:
            self._handle = None
            handle.close()

    def __enter__(self) -> BackendRuntimeFileLock:
        self.acquire()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.release()


@contextmanager
def backend_runtime_lock(
    project_root: str | Path,
    *,
    timeout_seconds: float = DEFAULT_BACKEND_RUNTIME_LOCK_TIMEOUT_SECONDS,
    poll_interval_seconds: float = DEFAULT_BACKEND_RUNTIME_LOCK_POLL_SECONDS,
    mode: BackendRuntimeLockMode = "exclusive",
) -> Iterator[Path]:
    lock_path = backend_runtime_lock_path(project_root)
    normalized = _normalized_lock_path(lock_path)
    held_modes = _locally_held_modes()
    existing_mode = held_modes.get(normalized)
    if existing_mode is not None:
        if existing_mode == "shared" and mode == "exclusive":
            raise RuntimeError(
                "cannot upgrade an active shared backend runtime lock to exclusive"
            )
        yield lock_path
        return

    file_lock = BackendRuntimeFileLock(
        lock_path,
        mode=mode,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    with file_lock:
        held_modes[normalized] = mode
        try:
            yield lock_path
        finally:
            held_modes.pop(normalized, None)

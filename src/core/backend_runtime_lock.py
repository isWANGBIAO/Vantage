from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import threading
import time
from typing import Iterator, Mapping, MutableMapping


BACKEND_RUNTIME_LOCK_NAME = ".vantage-backend-runtime.lock"
BACKEND_RUNTIME_LOCK_HELD_ENV = "VANTAGE_BACKEND_RUNTIME_LOCK_HELD"
DEFAULT_BACKEND_RUNTIME_LOCK_TIMEOUT_SECONDS = 300.0
DEFAULT_BACKEND_RUNTIME_LOCK_POLL_SECONDS = 0.05

_thread_state = threading.local()


def backend_runtime_lock_path(project_root: str | Path) -> Path:
    return Path(project_root).resolve() / BACKEND_RUNTIME_LOCK_NAME


def _normalized_lock_path(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def backend_runtime_lock_is_inherited(
    project_root: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> bool:
    resolved_environ = os.environ if environ is None else environ
    held_path = resolved_environ.get(BACKEND_RUNTIME_LOCK_HELD_ENV)
    if not held_path:
        return False
    return _normalized_lock_path(held_path) == _normalized_lock_path(
        backend_runtime_lock_path(project_root)
    )


def _locally_held_paths() -> set[str]:
    held_paths = getattr(_thread_state, "held_paths", None)
    if held_paths is None:
        held_paths = set()
        _thread_state.held_paths = held_paths
    return held_paths


def backend_runtime_lock_is_held(
    project_root: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> bool:
    normalized = _normalized_lock_path(backend_runtime_lock_path(project_root))
    return normalized in _locally_held_paths() or backend_runtime_lock_is_inherited(
        project_root,
        environ=environ,
    )


class BackendRuntimeFileLock:
    def __init__(
        self,
        path: str | Path,
        *,
        timeout_seconds: float = DEFAULT_BACKEND_RUNTIME_LOCK_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_BACKEND_RUNTIME_LOCK_POLL_SECONDS,
        monotonic=time.monotonic,
        sleep=time.sleep,
    ) -> None:
        if timeout_seconds < 0:
            raise ValueError("backend runtime lock timeout must be non-negative")
        if poll_interval_seconds <= 0:
            raise ValueError("backend runtime lock poll interval must be positive")
        self.path = Path(path)
        self.timeout_seconds = float(timeout_seconds)
        self.poll_interval_seconds = float(poll_interval_seconds)
        self._monotonic = monotonic
        self._sleep = sleep
        self._handle = None

    def _try_lock(self) -> bool:
        assert self._handle is not None
        if os.name == "nt":
            import msvcrt

            try:
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    return False
                raise
            return True

        import fcntl

        try:
            fcntl.flock(
                self._handle.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            return False
        return True

    def acquire(self) -> None:
        if self._handle is not None:
            raise RuntimeError("backend runtime lock is already acquired")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
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
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
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
    environ: MutableMapping[str, str] | None = None,
) -> Iterator[Path]:
    lock_path = backend_runtime_lock_path(project_root)
    normalized = _normalized_lock_path(lock_path)
    held_paths = _locally_held_paths()
    resolved_environ = os.environ if environ is None else environ
    if normalized in held_paths or backend_runtime_lock_is_inherited(
        project_root,
        environ=resolved_environ,
    ):
        yield lock_path
        return

    file_lock = BackendRuntimeFileLock(
        lock_path,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    with file_lock:
        held_paths.add(normalized)
        try:
            yield lock_path
        finally:
            held_paths.remove(normalized)


def inherited_backend_runtime_lock_environment(
    project_root: str | Path,
    *,
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = dict(os.environ if base_environment is None else base_environment)
    environment[BACKEND_RUNTIME_LOCK_HELD_ENV] = str(
        backend_runtime_lock_path(project_root)
    )
    return environment

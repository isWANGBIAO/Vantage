"""Private, local-only Python crash evidence, initialized before service imports.

Exception values, source lines, arguments and locals are deliberately omitted.
Native fault stacks and paths may still reveal private information. This module
never uploads records and never changes Windows error-reporting settings.
"""
from __future__ import annotations

import atexit
import faulthandler
import os
from pathlib import Path
import re
import stat
import sys
import threading
import time
import uuid

from src.core.config import Config

MAX_RECORDS = 10
MAX_BYTES = 200 * 1024 * 1024
MAX_TEXT_RECORD_BYTES = 512 * 1024
NATIVE_WRITE_GRACE_SECONDS = 30
_CURRENT = None
_ACTIVE_NAME = re.compile(r"^(?:backend|run-prompt|cli|face-analysis)-(\d+)-[^/]+\.active\.log$")


def _is_link(st):
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def _safe_directory(path: Path, *, create=False):
    try:
        if create:
            path.mkdir(exist_ok=True)
        info = path.lstat()
        return stat.S_ISDIR(info.st_mode) and not _is_link(info)
    except OSError:
        return False


def _walk_regular_files(root: Path):
    """Do not follow symlinks, junctions, reparse points or nonregular files."""
    if not _safe_directory(root):
        return
    pending = [root]
    while pending:
        directory = pending.pop()
        if not _safe_directory(directory):
            continue
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        # Windows DirEntry.stat may cache st_ino=0; lstat is
                        # needed for stable identity revalidation before cleanup.
                        info = Path(entry.path).lstat()
                    except OSError:
                        continue
                    if _is_link(info):
                        continue
                    path = Path(entry.path)
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(path)
                    elif stat.S_ISREG(info.st_mode):
                        yield path, info
        except OSError:
            continue


def _report_file(path):
    return (path.suffix == ".dmp" or path.suffix == ".log"
            or (path.suffix == ".json" and path.name.startswith("incident-")))


def _safe_parent_chain(path, root):
    parent = path.parent
    while parent != root:
        if not _safe_directory(parent) or parent == parent.parent:
            return False
        parent = parent.parent
    return _safe_directory(root)


def _same_file_snapshot(current, expected):
    return (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) == (
        expected.st_dev, expected.st_ino, expected.st_size, expected.st_mtime_ns
    )


def _safe_unlink(path, root, expected):
    try:
        if not _safe_parent_chain(path, root):
            return False
        current = path.lstat()
        if _is_link(current) or not stat.S_ISREG(current.st_mode):
            return False
        if not _same_file_snapshot(current, expected):
            return False
        path.unlink()
        return True
    except (OSError, ValueError):
        return False


def _safe_complete_record(path, root, expected):
    try:
        if not _safe_parent_chain(path, root):
            return False
        current = path.lstat()
        if _is_link(current) or not stat.S_ISREG(current.st_mode) or not _same_file_snapshot(current, expected):
            return False
        path.rename(path.with_name(path.name.replace(".active.log", ".log")))
        return True
    except OSError:
        return False


def prune_diagnostics(directory, *, max_records=MAX_RECORDS, max_bytes=MAX_BYTES):
    """Bound completed reports across Electron/Python, never remove active files.

    Active bytes count against the budget, but an oversized live record cannot be
    removed safely. The budget is enforced as soon as that record is completed.
    """
    root = Path(directory)
    completed = []
    total = 0
    now = time.time()
    for path, info in _walk_regular_files(root):
        if not _report_file(path):
            continue
        total += info.st_size
        # Crashpad's generic (POSIX) database writes in new/ and moves a report
        # to pending/ only after closing the writer. Age is not sufficient there.
        native_still_writing = path.suffix == ".dmp" and (
            "new" in path.relative_to(root).parent.parts
            or now - info.st_mtime < NATIVE_WRITE_GRACE_SECONDS
        )
        if ".active." not in path.name and not native_still_writing:
            completed.append((info.st_mtime_ns, str(path), path, info))
    completed.sort()
    count = len(completed)
    for _, _, path, info in completed:
        if count <= max_records and total <= max_bytes:
            break
        if _safe_unlink(path, root, info):
            count -= 1
            total -= info.st_size


def _process_alive(pid):
    if pid <= 0:
        return True  # Unknown identity: retain rather than risk deleting live evidence.
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER = nonexistent pid.
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def recover_stale_python_records(directory):
    root = Path(directory)
    for path, info in _walk_regular_files(root):
        match = _ACTIVE_NAME.match(path.name)
        if not match or _process_alive(int(match.group(1))):
            continue
        try:
            if info.st_size == 0:
                _safe_unlink(path, root, info)
            else:
                # UUID names prevent collisions; compare size/mtime too, because
                # a report modified after enumeration is not completed evidence.
                _safe_complete_record(path, root, info)
        except OSError:
            pass


class CrashDiagnostics:
    def __init__(self, root, role, periodic_seconds):
        self.root = root
        self.pid = os.getpid()
        self.path = root / "python" / f"{role}-{self.pid}-{uuid.uuid4().hex}.active.log"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        self.handle = os.fdopen(os.open(self.path, flags, 0o600), "w", encoding="utf-8")
        self._lock = threading.RLock()
        self._closed = False
        self._stop = threading.Event()
        self._old_sys_hook = sys.excepthook
        self._old_thread_hook = threading.excepthook
        self._sys_hook = self._on_exception
        self._thread_hook = self._on_thread_exception
        try:
            faulthandler.enable(file=self.handle, all_threads=True)
        except (OSError, ValueError, RuntimeError):
            self.handle.close()
            try:
                _safe_unlink(self.path, self.root, self.path.lstat())
            except OSError:
                pass
            raise
        sys.excepthook = self._sys_hook
        threading.excepthook = self._thread_hook
        atexit.register(self.close)
        if periodic_seconds > 0:
            def maintenance():
                while not self._stop.wait(periodic_seconds):
                    recover_stale_python_records(self.root / "python")
                    prune_diagnostics(self.root)
            threading.Thread(target=maintenance, name="Vantage-diagnostics-retention", daemon=True).start()

    def _on_exception(self, exception_type, value, traceback):
        if exception_type is KeyboardInterrupt:
            return
        self._write_exception("uncaught-exception", exception_type, traceback)

    def _on_thread_exception(self, args):
        if args.exc_type is not SystemExit:
            self._write_exception("thread-exception", args.exc_type, args.exc_traceback)

    def _write_exception(self, kind, exception_type, traceback):
        # Do not call traceback.format_exception: it includes values and source.
        lines = [f"{kind} {exception_type.__name__} UTC={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"]
        frames = 0
        while traceback is not None and frames < 128:
            code = traceback.tb_frame.f_code
            lines.append(f"  File {code.co_filename!r}, line {traceback.tb_lineno}, in {code.co_name}\n")
            traceback = traceback.tb_next
            frames += 1
        with self._lock:
            try:
                if not self._closed and os.fstat(self.handle.fileno()).st_size < MAX_TEXT_RECORD_BYTES:
                    self.handle.write("".join(lines))
                    self.handle.flush()
                    os.fsync(self.handle.fileno())
            except (OSError, ValueError):
                pass

    def close(self):
        global _CURRENT
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._stop.set()
            if sys.excepthook is self._sys_hook:
                sys.excepthook = self._old_sys_hook
            if threading.excepthook is self._thread_hook:
                threading.excepthook = self._old_thread_hook
            faulthandler.disable()
            self.handle.close()
            try:
                info = self.path.lstat()
                if not _is_link(info) and _safe_parent_chain(self.path, self.root):
                    if info.st_size:
                        _safe_complete_record(self.path, self.root, info)
                    else:
                        _safe_unlink(self.path, self.root, info)
            except OSError:
                pass
            prune_diagnostics(self.root)
            if _CURRENT is self:
                _CURRENT = None


def install_crash_diagnostics(*, role="backend", periodic_seconds=60):
    """Fail open on storage errors so diagnostics cannot block app startup."""
    global _CURRENT
    if _CURRENT is not None and _CURRENT.pid == os.getpid():
        return _CURRENT
    if role not in {"backend", "run-prompt", "cli", "face-analysis"}:
        role = "backend"
    try:
        Config.load_env()
        root = Config.get_data_dir() / "diagnostics"
        if not _safe_directory(root, create=True) or not _safe_directory(root / "python", create=True):
            return None
        recover_stale_python_records(root / "python")
        prune_diagnostics(root)
        _CURRENT = CrashDiagnostics(root, role, periodic_seconds)
        return _CURRENT
    except (OSError, ValueError, RuntimeError):
        return None

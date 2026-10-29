"""Small local-only exit observer. No application services or third-party imports.

This observer cannot identify a terminating actor or survive power/storage loss.
It never terminates or restarts an observed process.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import uuid

MAX_STATE_BYTES = 16384
MAX_HISTORY_RECORDS = 100
MAX_HISTORY_BYTES = 5 * 1024 * 1024


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _directory(path, create=False):
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if _linked(info) or not stat.S_ISDIR(info.st_mode):
        raise ValueError('unsafe-diagnostics-directory')


def _session_root(path):
    path = Path(os.path.abspath(path))
    if path.parent.name != 'sessions' or path.parent.parent.name != 'diagnostics':
        raise ValueError('invalid-session-location')
    for parent in (path.parent.parent, path.parent):
        _directory(parent)
    suffix = '.active.json'
    if not path.name.endswith(suffix):
        raise ValueError('invalid-session-filename')
    sid = path.name[:-len(suffix)]
    if str(uuid.UUID(sid)) != sid:
        raise ValueError('invalid-session-id')
    return path, path.parent.parent, sid


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('invalid-timestamp')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('invalid-timestamp')
    return value


def _pid(value, nullable=False):
    if nullable and value is None:
        return None
    if type(value) is not int or not 0 < value < 2**32:
        raise ValueError('invalid-pid')
    return value


def open_shared_read(path):
    if sys.platform != 'win32':
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        return os.fdopen(fd, 'r', encoding='utf-8')
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    # Share deletion and keep this handle very short-lived. Windows replacement
    # can still require a brief writer retry. Do not follow a swapped reparse point.
    handle = kernel.CreateFileW(str(path), 0x80000000, 7, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    return os.fdopen(fd, 'r', encoding='utf-8')


class SnapshotChanged(ValueError):
    """A legitimate atomic publication raced a short reader."""


def read_session(path):
    for attempt in range(4):
        try:
            return _read_session_once(path)
        except SnapshotChanged:
            if attempt == 3:
                raise


def _read_session_once(path):
    path, _, sid = _session_root(path)
    info = path.lstat()
    if _linked(info) or not stat.S_ISREG(info.st_mode) or info.st_size > MAX_STATE_BYTES:
        raise ValueError('unsafe-session-file')
    with open_shared_read(path) as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or _linked(opened):
            raise ValueError('unsafe-opened-session')
        if (opened.st_ino, opened.st_dev) != (info.st_ino, info.st_dev):
            raise SnapshotChanged('session-publication-raced-read')
        content = stream.read(MAX_STATE_BYTES + 1)
        if len(content.encode('utf-8')) > MAX_STATE_BYTES:
            raise ValueError('oversized-session')
        value = json.loads(content)
    if not isinstance(value, dict) or value.get('schemaVersion') != 1 or value.get('sessionId') != sid:
        raise ValueError('invalid-session-identity')
    if value.get('phase') not in ('running', 'shutting-down', 'clean'):
        raise ValueError('invalid-session-phase')
    result = dict(schemaVersion=1, sessionId=sid, pid=_pid(value.get('pid')),
                  parentPid=_pid(value.get('parentPid'), nullable=True),
                  backendPid=_pid(value.get('backendPid'), nullable=True),
                  phase=value['phase'], startedAt=_timestamp(value.get('startedAt')),
                  lastHeartbeatAt=_timestamp(value.get('lastHeartbeatAt')))
    if value.get('backendStartedAt') is not None:
        result['backendStartedAt'] = _timestamp(value['backendStartedAt'])
    return result


def atomic_json(path, value):
    if path.parent.name != 'lifecycle' or path.parent.parent.name != 'diagnostics':
        raise ValueError('invalid-output-location')
    _directory(path.parent.parent)
    _directory(path.parent)
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if _linked(info) or not stat.S_ISREG(info.st_mode):
            raise ValueError('unsafe-output-file')
    temp = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        with temp.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, separators=(',', ':'))
            stream.flush()
            os.fsync(stream.fileno())
        _directory(path.parent.parent)
        _directory(path.parent)
        deadline = time.monotonic() + .05
        for attempt in range(11):
            try:
                os.replace(temp, path)
                break
            except OSError as error:
                if error.errno not in (1, 13, 16) or attempt == 10 or time.monotonic() >= deadline:
                    raise
                time.sleep(.004)
    finally:
        temp.unlink(missing_ok=True)


def prune_history(directory, max_records=MAX_HISTORY_RECORDS, max_bytes=MAX_HISTORY_BYTES):
    _directory(directory.parent)
    _directory(directory)
    files = []
    for path in directory.glob('exit-*.json'):
        try:
            info = path.lstat()
            if not _linked(info) and stat.S_ISREG(info.st_mode):
                files.append((info.st_mtime_ns, path.name, path, info))
        except FileNotFoundError:
            pass
    total = sum(item[3].st_size for item in files)
    count = len(files)
    for _, _, path, info in sorted(files):
        if count <= max_records and total <= max_bytes:
            break
        try:
            _directory(directory.parent)
            _directory(directory)
            current = path.lstat()
            if (current.st_ino, current.st_dev, current.st_mtime_ns, current.st_size) != (
                    info.st_ino, info.st_dev, info.st_mtime_ns, info.st_size) or _linked(current):
                continue
            path.unlink()
            count -= 1
            total -= info.st_size
        except FileNotFoundError:
            pass


def record_exit(session_path, state, role, *, pid, exit_code, observed_at=None,
                created_at=None):
    _, root, sid = _session_root(session_path)
    directory = root / 'lifecycle'
    _directory(directory, create=True)
    if role not in ('main', 'backend'):
        raise ValueError('invalid-process-role')
    _pid(pid)
    if exit_code is not None and (type(exit_code) is not int or not 0 <= exit_code < 2**32):
        raise ValueError('invalid-exit-code')
    if exit_code is None:
        reason = 'unobserved-exit'
    elif role == 'backend' and state['phase'] in ('shutting-down', 'clean'):
        reason = 'expected-exit'
    elif exit_code == 0 and state['phase'] == 'clean':
        reason = 'normal-exit'
    else:
        reason = 'unexpected-exit'
    value = dict(schemaVersion=1, sessionId=sid, source='observer', processType=role,
                 pid=pid, parentPid=state['pid'] if role == 'backend' else state.get('parentPid'),
                 phase=state['phase'], reason=reason,
                 exitCode=exit_code, exitAt=(observed_at or utc_now()) if exit_code is not None else None,
                 detectedAt=utc_now(), startedAt=state.get('backendStartedAt') if role == 'backend' else state['startedAt'],
                 lastHeartbeatAt=state['lastHeartbeatAt'], processCreatedAt=created_at)
    atomic_json(directory / f'exit-{sid}-{role}-{pid}.json', value)
    prune_history(directory)
    return value


class WindowsProcess:
    """An opened process handle retains identity even after PID reuse."""
    def __init__(self, pid):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        self.kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        self.kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.handle = self.kernel.OpenProcess(0x100000 | 0x1000, False, _pid(pid))
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.pid = pid
        creation, end, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not self.kernel.GetProcessTimes(self.handle, *(ctypes.byref(v) for v in (creation, end, kernel, user))):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        self.created_at = datetime.fromtimestamp(ticks / 10**7 - 11644473600, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    def exit_code(self):
        from ctypes import wintypes
        wait = self.kernel.WaitForSingleObject(self.handle, 0)
        if wait == 258:
            return None
        if wait != 0:
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        code = wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle, self.ctypes.byref(code)):
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        return code.value

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def probe_process(pid, registered_at, process_factory=WindowsProcess):
    _pid(pid)
    _timestamp(registered_at)
    try:
        handle = process_factory(pid)
    except OSError as error:
        # Access denied is unknown, never evidence that an old owner is dead.
        return dict(pid=pid, alive=False if getattr(error, 'winerror', error.errno) == 87 else None)
    try:
        created = datetime.fromisoformat(handle.created_at.replace('Z', '+00:00'))
        registered = datetime.fromisoformat(registered_at.replace('Z', '+00:00'))
        return dict(pid=pid, alive=handle.exit_code() is None and created <= registered)
    finally:
        handle.close()


def _ack(path, status, **details):
    _, root, sid = _session_root(path)
    directory = root / 'lifecycle'
    _directory(directory, create=True)
    value = dict(schemaVersion=1, sessionId=sid, status=status, pid=os.getpid(),
                 isolation=details.get('isolation', 'unknown'), recordedAt=utc_now())
    if details.get('reason') in ('unsupported-platform', 'observer-failed'):
        value['reason'] = details['reason']
    atomic_json(directory / f'watcher-{sid}.json', value)
    return value


def watch(session_path, isolation='unknown', process_factory=WindowsProcess):
    if sys.platform != 'win32':
        _ack(session_path, 'failed', reason='unsupported-platform')
        return 2
    state = read_session(session_path)
    handles, observed = {}, set()
    last_ack = 0
    try:
        while True:
            state = read_session(session_path)
            for role, pid in (('main', state['pid']), ('backend', state['backendPid'])):
                if not pid or (role, pid) in observed or role in handles:
                    continue
                try:
                    handle = process_factory(pid)
                    registered = state['startedAt'] if role == 'main' else state.get('backendStartedAt')
                    if registered and datetime.fromisoformat(handle.created_at.replace('Z', '+00:00')) > datetime.fromisoformat(registered.replace('Z', '+00:00')):
                        handle.close()
                        raise ValueError('process-identity-changed')
                    handles[role] = handle
                except (OSError, ValueError) as error:
                    record_exit(session_path, state, role, pid=pid, exit_code=None)
                    observed.add((role, pid))
                    already_gone = isinstance(error, OSError) and getattr(error, 'winerror', error.errno) == 87
                    if role == 'main' or not already_gone:
                        _ack(session_path, 'failed', isolation=isolation, reason='observer-failed')
                        return 2
            if not observed and not handles:
                raise ValueError('no-observable-processes')
            if time.monotonic() - last_ack >= 2:
                _ack(session_path, 'ready', isolation=isolation)
                last_ack = time.monotonic()
            for role, handle in list(handles.items()):
                code = handle.exit_code()
                if code is None:
                    continue
                state = read_session(session_path)
                record_exit(session_path, state, role, pid=handle.pid, exit_code=code,
                            created_at=handle.created_at)
                observed.add((role, handle.pid))
                handle.close()
                del handles[role]
            if ('main', state['pid']) in observed and not handles:
                return 0
            time.sleep(.2)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        _ack(session_path, 'failed', isolation=isolation, reason='observer-failed')
        return 2
    finally:
        for handle in handles.values():
            handle.close()


def launch_observer(session_path, *, command=None, popen=subprocess.Popen, platform=sys.platform):
    read_session(session_path)
    if platform != 'win32':
        return _ack(session_path, 'failed', reason='unsupported-platform')
    if command is None:
        command = ([sys.executable, '--diagnostics-watch'] if getattr(sys, 'frozen', False)
                   else [sys.executable, '-m', 'src.core.exit_observer', '--watch'])
    flags = 0x08000000 | 0x00000200 | 0x00000008
    kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, close_fds=True)
    isolation = 'breakaway'
    try:
        child = popen([*command, str(session_path), '--isolation', isolation],
                      creationflags=flags | 0x01000000, **kwargs)
    except PermissionError:
        isolation = 'inherited-job'
        child = popen([*command, str(session_path), '--isolation', isolation], creationflags=flags, **kwargs)
    return dict(status='starting', isolation=isolation, pid=child.pid)


def main(argv=None):
    # Mode names intentionally start with --; parse the first token explicitly.
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == '--diagnostics-probe':
        if len(args) != 3 or sys.platform != 'win32':
            return 2
        try:
            result = probe_process(int(args[1]), args[2])
            print(json.dumps(result))
            return 0 if result['alive'] is not None else 2
        except (ValueError, OSError):
            return 2
    if not args or args[0] not in ('--launch', '--watch', '--diagnostics-launch', '--diagnostics-watch'):
        return 2
    mode = args.pop(0)
    options = argparse.ArgumentParser()
    options.add_argument('session')
    options.add_argument('--isolation', choices=('breakaway', 'inherited-job', 'unknown'), default='unknown')
    parsed = options.parse_args(args)
    try:
        if mode in ('--launch', '--diagnostics-launch'):
            result = launch_observer(parsed.session)
            return 0 if result['status'] == 'starting' else 2
        return watch(parsed.session, parsed.isolation)
    except (OSError, ValueError):
        try:
            _ack(parsed.session, 'failed', reason='observer-failed')
        except (OSError, ValueError):
            pass
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

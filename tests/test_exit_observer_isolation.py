"""Real desktop isolation acceptance; every terminated process is test-owned."""
import ctypes as c
from ctypes import wintypes as w
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pytest


def _eventually(read, predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = read()
            if predicate(value):
                return value
        except (FileNotFoundError, PermissionError, json.JSONDecodeError):
            pass
        time.sleep(.05)
    pytest.fail('synthetic observer acceptance condition timed out')


def _kernel():
    kernel = c.WinDLL('kernel32', use_last_error=True)
    for name, args, result in (
        ('CreateJobObjectW', (c.c_void_p, w.LPCWSTR), w.HANDLE),
        ('SetInformationJobObject', (w.HANDLE, c.c_int, c.c_void_p, w.DWORD), w.BOOL),
        ('AssignProcessToJobObject', (w.HANDLE, w.HANDLE), w.BOOL),
        ('OpenProcess', (w.DWORD, w.BOOL, w.DWORD), w.HANDLE),
        ('CloseHandle', (w.HANDLE,), w.BOOL),
        ('TerminateProcess', (w.HANDLE, w.UINT), w.BOOL),
        ('WaitForSingleObject', (w.HANDLE, w.DWORD), w.DWORD),
        ('GetExitCodeProcess', (w.HANDLE, c.POINTER(w.DWORD)), w.BOOL),
    ):
        function = getattr(kernel, name)
        function.argtypes, function.restype = args, result
    return kernel


class _BasicJobLimits(c.Structure):
    _fields_ = [('processTime', c.c_longlong), ('jobTime', c.c_longlong),
                ('flags', w.DWORD), ('minimumWorkingSet', c.c_size_t),
                ('maximumWorkingSet', c.c_size_t), ('activeProcessLimit', w.DWORD),
                ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]


class _ExtendedJobLimits(c.Structure):
    _fields_ = [('basic', _BasicJobLimits), ('ioCounters', c.c_ulonglong * 6),
                ('processMemoryLimit', c.c_size_t), ('jobMemoryLimit', c.c_size_t),
                ('peakProcessMemory', c.c_size_t), ('peakJobMemory', c.c_size_t)]


@pytest.mark.skipif(sys.platform != 'win32', reason='native interactive Windows desktop acceptance')
def test_observer_survives_launcher_job_close_and_records_owned_main_exit(tmp_path):
    from src.core.exit_observer import open_shared_read
    from src.core.windows_process_launch import inspect_process

    kernel = _kernel()
    root = Path(__file__).resolve().parents[1]
    main = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'],
                            creationflags=subprocess.CREATE_NO_WINDOW)
    launcher = None
    observer_handle = None
    job = None
    result_path = tmp_path / 'launcher-result.json'
    sid = str(uuid.uuid4())
    session = tmp_path / 'diagnostics' / 'sessions' / f'{sid}.active.json'
    session.parent.mkdir(parents=True)
    now = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    session.write_text(json.dumps(dict(schemaVersion=1, sessionId=sid, pid=main.pid,
        parentPid=os.getpid(), backendPid=None, phase='running', startedAt=now,
        lastHeartbeatAt=now)), encoding='utf-8')
    lifecycle = session.parent.parent / 'lifecycle'
    ack_path = lifecycle / f'watcher-{sid}.json'
    record_path = lifecycle / f'exit-{sid}-main-{main.pid}.json'

    def read_json(path):
        with open_shared_read(path) as stream:
            return json.load(stream)

    script = '''import json,pathlib,sys
from src.core.exit_observer import launch_observer
sys.stdin.readline()
result=launch_observer(sys.argv[1])
path=pathlib.Path(sys.argv[2])
temp=path.with_suffix('.tmp')
temp.write_text(json.dumps(result),encoding='utf-8')
temp.replace(path)
sys.stdin.readline()
'''
    try:
        launcher = subprocess.Popen([sys.executable, '-u', '-c', script, str(session), str(result_path)],
            cwd=str(root), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        job = kernel.CreateJobObjectW(None, None)
        assert job
        limits = _ExtendedJobLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        assert kernel.SetInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits))
        assert kernel.AssignProcessToJobObject(job, int(launcher._handle))
        launcher.stdin.write('start\n')
        launcher.stdin.flush()

        result = _eventually(lambda: read_json(result_path), lambda value: value.get('status') == 'starting')
        observer_handle = kernel.OpenProcess(0x101001, False, result['pid'])
        assert observer_handle, 'retain only the known synthetic observer handle'
        initial_ack = _eventually(lambda: read_json(ack_path), lambda value: value.get('status') == 'ready')
        assert initial_ack['pid'] == result['pid']
        assert initial_ack['isolation'] == 'desktop-independent'
        identity = initial_ack['identity']
        assert identity['inJob'] is False
        assert identity['hasPackageIdentity'] is False
        assert identity['parentIsShell'] is True
        assert identity['isIndependent'] is True
        assert inspect_process(result['pid'])['isIndependent'] is True

        assert kernel.CloseHandle(job)
        job = None
        launcher.wait(timeout=5)
        assert launcher.returncode is not None
        assert kernel.WaitForSingleObject(observer_handle, 100) == 258
        later_ack = _eventually(lambda: read_json(ack_path),
            lambda value: value.get('status') == 'ready' and value['recordedAt'] > initial_ack['recordedAt'])
        assert later_ack['pid'] == result['pid']
        assert later_ack['identity'] == identity

        expected_exit_code = 0xE1
        assert kernel.TerminateProcess(int(main._handle), expected_exit_code)
        assert main.wait(timeout=5) == expected_exit_code
        record = _eventually(lambda: read_json(record_path), lambda value: value.get('exitCode') == expected_exit_code)
        assert record['source'] == 'observer'
        assert record['processType'] == 'main'
        assert record['pid'] == main.pid
        assert record['sessionId'] == sid
        assert record['reason'] == 'unexpected-exit'
        assert record['processCreatedAt']
        assert kernel.WaitForSingleObject(observer_handle, 5000) == 0
        observer_code = w.DWORD()
        assert kernel.GetExitCodeProcess(observer_handle, c.byref(observer_code))
        assert observer_code.value == 0
    finally:
        # No process-name lookup or broad process-tree termination is allowed.
        if observer_handle:
            if kernel.WaitForSingleObject(observer_handle, 0) == 258:
                kernel.TerminateProcess(observer_handle, 0)
                kernel.WaitForSingleObject(observer_handle, 5000)
            kernel.CloseHandle(observer_handle)
        if launcher is not None:
            if launcher.poll() is None:
                launcher.kill()
                launcher.wait(timeout=5)
            if launcher.stdin:
                launcher.stdin.close()
        if job:
            kernel.CloseHandle(job)
        if main.poll() is None:
            main.kill()
            main.wait(timeout=5)

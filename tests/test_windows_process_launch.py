"""Only synthetic process handles are terminated; never a desktop application."""
from datetime import datetime
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


def _desktop_unavailable():
    if sys.platform != 'win32':
        return True
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetShellWindow.argtypes = ()
    user.GetShellWindow.restype = wintypes.HWND
    # A service CI runner may have no interactive shell. Other native failures
    # are not converted into skips, and this is not installed-app acceptance.
    return not user.GetShellWindow()


def module():
    try:
        return importlib.import_module('src.core.windows_process_launch')
    except ModuleNotFoundError:
        pytest.fail('verified desktop-independent launcher is not implemented')


def test_invalid_input_is_rejected_without_echoing_secrets():
    launcher = module()
    for command in ([], ['PRIVATE_SECRET'], [sys.executable, 'unsafe\0PRIVATE_SECRET']):
        with pytest.raises(launcher.WindowsLaunchError) as caught:
            launcher.launch_from_desktop(command)
        assert 'PRIVATE_SECRET' not in str(caught.value)


def test_native_failures_are_controlled_and_do_not_echo_arguments(monkeypatch):
    launcher = module()
    def fail():
        raise OSError('PRIVATE_SECRET')
    monkeypatch.setattr(launcher, '_WindowsAPI', fail)
    with pytest.raises(launcher.WindowsLaunchError) as caught:
        launcher.launch_from_desktop([sys.executable, '-c', 'PRIVATE_SECRET'])
    assert 'PRIVATE_SECRET' not in str(caught.value)


def test_validation_failures_are_controlled(monkeypatch):
    launcher = module()
    def fail(_path):
        raise OSError('PRIVATE_SECRET')
    monkeypatch.setattr(launcher.Path, 'is_file', fail)
    with pytest.raises(launcher.WindowsLaunchError) as caught:
        launcher.launch_from_desktop([sys.executable])
    assert 'PRIVATE_SECRET' not in str(caught.value)


def _wait_file(path, timeout=10):
    deadline = time.monotonic() + timeout
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(.025)
    assert path.exists(), 'synthetic child did not publish acceptance data'


def _owned_process(pid):
    import ctypes as c
    from ctypes import wintypes as w
    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (w.DWORD, w.BOOL, w.DWORD)
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = (w.HANDLE,)
    kernel.TerminateProcess.argtypes = (w.HANDLE, w.UINT)
    kernel.WaitForSingleObject.argtypes = (w.HANDLE, w.DWORD)
    handle = kernel.OpenProcess(0x101001, False, pid)
    assert handle, 'unable to retain the known synthetic child handle'
    return kernel, handle


@pytest.mark.skipif(_desktop_unavailable(), reason='requires Windows with an interactive Explorer shell')
def test_real_launch_is_outside_jobs_packages_and_has_shell_parent():
    launcher = module()
    result = launcher.launch_from_desktop([sys.executable, '-c', 'import time;time.sleep(30)'])
    kernel, handle = _owned_process(result['pid'])
    try:
        identity = launcher.inspect_process(result['pid'])
        assert result['isolation'] == 'desktop-independent'
        assert identity['inJob'] is False
        assert identity['hasPackageIdentity'] is False
        assert identity['parentIsShell'] is True
        assert identity['isIndependent'] is True
        assert datetime.fromisoformat(identity['createdAt'].replace('Z', '+00:00')).tzinfo
        assert set(identity) <= {'pid', 'parentPid', 'inJob', 'hasPackageIdentity', 'parentIsShell',
                                 'isIndependent', 'createdAt', 'sessionId'}
        assert 'explorer.exe' not in json.dumps(identity)
    finally:
        kernel.TerminateProcess(handle, 0)
        kernel.WaitForSingleObject(handle, 5000)
        kernel.CloseHandle(handle)


@pytest.mark.skipif(_desktop_unavailable(), reason='requires Windows with an interactive Explorer shell')
def test_unicode_arguments_environment_and_cwd_are_preserved(tmp_path):
    launcher = module()
    cwd = tmp_path / 'unicode 路径'
    cwd.mkdir()
    output = cwd / 'result.json'
    arg = 'space and "quoted" 参数\\'
    script = ('import json,os,pathlib,sys; pathlib.Path(sys.argv[1]).write_text('
              'json.dumps(dict(arg=sys.argv[2],value=os.environ.get("VANTAGE_TEST_VALUE"),cwd=os.getcwd())),encoding="utf-8");'
              'import time;time.sleep(30)')
    result = launcher.launch_from_desktop([sys.executable, '-c', script, str(output), arg],
        environment={'SystemRoot': os.environ['SystemRoot'], 'VANTAGE_TEST_VALUE': '安全=值'}, cwd=str(cwd))
    kernel, handle = _owned_process(result['pid'])
    try:
        assert result['identity']['isIndependent'] is True
        _wait_file(output)
        value = json.loads(output.read_text(encoding='utf-8'))
        assert value == {'arg': arg, 'value': '安全=值', 'cwd': str(cwd)}
    finally:
        kernel.TerminateProcess(handle, 0)
        kernel.WaitForSingleObject(handle, 5000)
        kernel.CloseHandle(handle)


@pytest.mark.skipif(_desktop_unavailable(), reason='requires Windows with an interactive Explorer shell')
def test_desktop_child_survives_kill_on_close_of_its_launcher_job():
    import ctypes as c
    from ctypes import wintypes as w
    launcher_api = module()
    root = str(Path(__file__).resolve().parents[1])
    body = '''import sys,json
sys.path.insert(0,sys.argv[1])
from src.core.windows_process_launch import launch_from_desktop
sys.stdin.readline()
result=launch_from_desktop([sys.executable,'-c','import time;time.sleep(30)'])
print(json.dumps(result),flush=True)
sys.stdin.readline()
'''
    launch = subprocess.Popen([sys.executable, '-u', '-c', body, root], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = (c.c_void_p, w.LPCWSTR)
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = (w.HANDLE, c.c_int, c.c_void_p, w.DWORD)
    kernel.AssignProcessToJobObject.argtypes = (w.HANDLE, w.HANDLE)
    kernel.TerminateJobObject.argtypes = (w.HANDLE, w.UINT)
    kernel.CloseHandle.argtypes = (w.HANDLE,)
    job = kernel.CreateJobObjectW(None, None)
    limits = c.create_string_buffer(144)
    w.DWORD.from_buffer(limits, 16).value = 0x2000
    target_handle = None
    try:
        assert kernel.SetInformationJobObject(job, 9, limits, c.sizeof(limits))
        assert kernel.AssignProcessToJobObject(job, int(launch._handle))
        launch.stdin.write('go\n'); launch.stdin.flush()
        line = launch.stdout.readline()
        assert line, launch.stderr.read()
        result = json.loads(line)
        target_kernel, target_handle = _owned_process(result['pid'])
        assert kernel.CloseHandle(job)
        job = None
        launch.wait(timeout=5)
        assert launch.returncode is not None
        assert target_kernel.WaitForSingleObject(target_handle, 100) == 258
        assert launcher_api.inspect_process(result['pid'])['isIndependent'] is True
    finally:
        if target_handle:
            target_kernel.TerminateProcess(target_handle, 0)
            target_kernel.WaitForSingleObject(target_handle, 5000)
            target_kernel.CloseHandle(target_handle)
        if launch.poll() is None:
            launch.kill(); launch.wait(timeout=5)
        if job:
            kernel.CloseHandle(job)
        for stream in (launch.stdin, launch.stdout, launch.stderr):
            if stream:
                stream.close()


@pytest.mark.skipif(_desktop_unavailable(), reason='requires Windows with an interactive Explorer shell')
def test_failed_independence_check_stops_only_new_suspended_child(monkeypatch, tmp_path):
    launcher = module()
    real_api = launcher._WindowsAPI
    owned = []
    marker = tmp_path / 'must-not-run.txt'
    class RejectIdentity(real_api):
        def identity(self, process, pid, shell_pid):
            owned.append(_owned_process(pid))
            result = super().identity(process, pid, shell_pid)
            result['isIndependent'] = False
            return result
    monkeypatch.setattr(launcher, '_WindowsAPI', RejectIdentity)
    try:
        with pytest.raises(launcher.WindowsLaunchError, match='^identity-check-failed$'):
            launcher.launch_from_desktop([sys.executable, '-c',
                'import pathlib,sys;pathlib.Path(sys.argv[1]).write_text("unexpected")', str(marker)])
        assert len(owned) == 1
        kernel, handle = owned[0]
        assert kernel.WaitForSingleObject(handle, 1000) == 0
        assert not marker.exists()
    finally:
        for kernel, handle in owned:
            kernel.TerminateProcess(handle, 0)
            kernel.WaitForSingleObject(handle, 5000)
            kernel.CloseHandle(handle)


@pytest.mark.skipif(_desktop_unavailable(), reason='requires Windows with an interactive Explorer shell')
def test_explicit_restrictive_policy_launcher_can_create_verified_desktop_child(tmp_path):
    """Policy 6 fixture is synthetic; it is not proof of an actual AppX update."""
    import ctypes as c
    from ctypes import wintypes as w
    launcher = module()
    api = launcher._WindowsAPI()
    output = tmp_path / 'policy-result.json'
    root = str(Path(__file__).resolve().parents[1])
    script = '''import sys,json,pathlib,time
sys.path.insert(0,sys.argv[1])
from src.core.windows_process_launch import launch_from_desktop,inspect_process
result=launch_from_desktop([sys.executable,'-c','import time;time.sleep(30)'])
result['launcher']=inspect_process()
pathlib.Path(sys.argv[2]).write_text(json.dumps(result),encoding='utf-8')
time.sleep(30)
'''
    size = c.c_size_t()
    api.kernel.InitializeProcThreadAttributeList(None, 1, 0, c.byref(size))
    attributes = c.create_string_buffer(size.value)
    assert api.kernel.InitializeProcThreadAttributeList(attributes, 1, 0, c.byref(size))
    child = launcher._PROCESS_INFORMATION()
    target_handle = None
    try:
        policy = w.DWORD(2 | 4)  # DISABLE_PROCESS_TREE | OVERRIDE, test fixture only.
        assert api.kernel.UpdateProcThreadAttribute(attributes, 0, 0x20012, c.byref(policy), c.sizeof(policy), None, None)
        startup = launcher._STARTUPINFOEX()
        startup.startup.cb = c.sizeof(startup)
        startup.attributes = c.cast(attributes, c.c_void_p)
        line = c.create_unicode_buffer(subprocess.list2cmdline([sys.executable, '-c', script, root, str(output)]))
        assert api.kernel.CreateProcessW(sys.executable, line, None, None, False,
            0x00080000 | 0x00000004 | 0x08000000, None, root, c.byref(startup), c.byref(child))
        assert api.kernel.ResumeThread(child.thread) != 0xffffffff
        _wait_file(output)
        result = json.loads(output.read_text(encoding='utf-8'))
        target_kernel, target_handle = _owned_process(result['pid'])
        assert result['identity']['isIndependent'] is True
        assert launcher.inspect_process(result['pid'])['isIndependent'] is True
        # End only the retained synthetic launcher, then prove target survival.
        assert api.kernel.TerminateProcess(child.process, 225)
        assert api.kernel.WaitForSingleObject(child.process, 5000) == 0
        assert target_kernel.WaitForSingleObject(target_handle, 100) == 258
    finally:
        if target_handle:
            target_kernel.TerminateProcess(target_handle, 0)
            target_kernel.WaitForSingleObject(target_handle, 5000)
            target_kernel.CloseHandle(target_handle)
        if child.process:
            api.kernel.TerminateProcess(child.process, 0)
            api.kernel.WaitForSingleObject(child.process, 5000)
            api.kernel.CloseHandle(child.process)
        if child.thread:
            api.kernel.CloseHandle(child.thread)
        api.kernel.DeleteProcThreadAttributeList(attributes)

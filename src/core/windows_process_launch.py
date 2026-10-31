"""Verified launches from the interactive desktop, not the invoking app's tree.

Uses the existing same-user Explorer as the documented process parent. No token
editing, service, scheduled task, elevation, or security-policy change is used.
"""
from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys


class WindowsLaunchError(RuntimeError):
    """Controlled enum-only failure, deliberately omitting paths and arguments."""


def _require(success, reason):
    if not success:
        raise WindowsLaunchError(reason)


class _STARTUPINFO(c.Structure):
    _fields_ = [
        ('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR), ('title', w.LPWSTR),
        ('x', w.DWORD), ('y', w.DWORD), ('xsize', w.DWORD), ('ysize', w.DWORD),
        ('xchars', w.DWORD), ('ychars', w.DWORD), ('fill', w.DWORD), ('flags', w.DWORD),
        ('show', w.WORD), ('reserved2size', w.WORD), ('reserved2', c.POINTER(c.c_byte)),
        ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE),
    ]


class _STARTUPINFOEX(c.Structure):
    _fields_ = [('startup', _STARTUPINFO), ('attributes', c.c_void_p)]


class _PROCESS_INFORMATION(c.Structure):
    _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]


class _PROCESSENTRY32(c.Structure):
    _fields_ = [
        ('size', w.DWORD), ('usage', w.DWORD), ('pid', w.DWORD), ('heap', c.c_size_t),
        ('module', w.DWORD), ('threads', w.DWORD), ('parentPid', w.DWORD),
        ('priority', w.LONG), ('flags', w.DWORD), ('image', w.WCHAR * 260),
    ]


class _SID_AND_ATTRIBUTES(c.Structure):
    _fields_ = [('sid', c.c_void_p), ('attributes', w.DWORD)]


class _WindowsAPI:
    def __init__(self):
        if sys.platform != 'win32':
            raise WindowsLaunchError('unsupported-platform')
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.user = c.WinDLL('user32', use_last_error=True)
        self.advapi = c.WinDLL('advapi32', use_last_error=True)
        k = self.kernel
        declarations = {
            'OpenProcess': ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            'CloseHandle': ([w.HANDLE], w.BOOL),
            'GetCurrentProcess': ([], w.HANDLE),
            'QueryFullProcessImageNameW': ([w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)], w.BOOL),
            'GetWindowsDirectoryW': ([w.LPWSTR, w.UINT], w.UINT),
            'ProcessIdToSessionId': ([w.DWORD, c.POINTER(w.DWORD)], w.BOOL),
            'CreateToolhelp32Snapshot': ([w.DWORD, w.DWORD], w.HANDLE),
            'Process32FirstW': ([w.HANDLE, c.POINTER(_PROCESSENTRY32)], w.BOOL),
            'Process32NextW': ([w.HANDLE, c.POINTER(_PROCESSENTRY32)], w.BOOL),
            'IsProcessInJob': ([w.HANDLE, w.HANDLE, c.POINTER(w.BOOL)], w.BOOL),
            'GetPackageFullName': ([w.HANDLE, c.POINTER(w.UINT), w.LPWSTR], w.LONG),
            'GetProcessTimes': ([w.HANDLE] + [c.POINTER(w.FILETIME)] * 4, w.BOOL),
            'InitializeProcThreadAttributeList': ([c.c_void_p, w.DWORD, w.DWORD, c.POINTER(c.c_size_t)], w.BOOL),
            'UpdateProcThreadAttribute': ([c.c_void_p, w.DWORD, c.c_size_t, c.c_void_p, c.c_size_t, c.c_void_p, c.c_void_p], w.BOOL),
            'DeleteProcThreadAttributeList': ([c.c_void_p], None),
            'CreateProcessW': ([w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p, w.BOOL, w.DWORD,
                                c.c_void_p, w.LPCWSTR, c.POINTER(_STARTUPINFOEX), c.POINTER(_PROCESS_INFORMATION)], w.BOOL),
            'ResumeThread': ([w.HANDLE], w.DWORD),
            'TerminateProcess': ([w.HANDLE, w.UINT], w.BOOL),
            'WaitForSingleObject': ([w.HANDLE, w.DWORD], w.DWORD),
        }
        for name, (arguments, result) in declarations.items():
            function = getattr(k, name)
            function.argtypes, function.restype = arguments, result
        self.user.GetShellWindow.argtypes, self.user.GetShellWindow.restype = [], w.HWND
        self.user.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
        self.user.GetWindowThreadProcessId.restype = w.DWORD
        self.advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
        self.advapi.OpenProcessToken.restype = w.BOOL
        self.advapi.GetTokenInformation.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
        self.advapi.GetTokenInformation.restype = w.BOOL
        self.advapi.GetLengthSid.argtypes, self.advapi.GetLengthSid.restype = [c.c_void_p], w.DWORD

    def session_id(self, pid):
        result = w.DWORD()
        _require(self.kernel.ProcessIdToSessionId(pid, c.byref(result)), 'process-unavailable')
        return result.value

    def sid(self, process):
        token = w.HANDLE()
        _require(self.advapi.OpenProcessToken(process, 8, c.byref(token)), 'shell-identity-unavailable')
        try:
            size = w.DWORD()
            self.advapi.GetTokenInformation(token, 1, None, 0, c.byref(size))
            _require(0 < size.value <= 65536, 'shell-identity-unavailable')
            value = c.create_string_buffer(size.value)
            _require(self.advapi.GetTokenInformation(token, 1, value, size, c.byref(size)), 'shell-identity-unavailable')
            sid = c.cast(value, c.POINTER(_SID_AND_ATTRIBUTES)).contents.sid
            length = self.advapi.GetLengthSid(sid)
            _require(0 < length <= 256, 'shell-identity-unavailable')
            return c.string_at(sid, length)
        finally:
            self.kernel.CloseHandle(token)

    def shell(self, create=False):
        window = self.user.GetShellWindow()
        _require(window, 'shell-unavailable')
        pid = w.DWORD()
        _require(self.user.GetWindowThreadProcessId(window, c.byref(pid)), 'shell-unavailable')
        access = 0x1000 | (0x0080 if create else 0)
        handle = self.kernel.OpenProcess(access, False, pid.value)
        _require(handle, 'shell-unavailable')
        try:
            _require(self.session_id(pid.value) == self.session_id(os.getpid()), 'shell-session-mismatch')
            _require(self.sid(handle) == self.sid(self.kernel.GetCurrentProcess()), 'shell-user-mismatch')
            size = w.DWORD(32768)
            image = c.create_unicode_buffer(size.value)
            _require(self.kernel.QueryFullProcessImageNameW(handle, 0, image, c.byref(size)), 'shell-identity-unavailable')
            windows = c.create_unicode_buffer(32768)
            length = self.kernel.GetWindowsDirectoryW(windows, len(windows))
            _require(0 < length < len(windows), 'shell-identity-unavailable')
            actual = os.path.normcase(os.path.realpath(image.value))
            expected = os.path.normcase(os.path.realpath(os.path.join(windows.value, 'explorer.exe')))
            _require(actual == expected, 'shell-image-mismatch')
            return pid.value, handle
        except BaseException:
            self.kernel.CloseHandle(handle)
            raise

    def parent_pid(self, pid):
        snapshot = self.kernel.CreateToolhelp32Snapshot(2, 0)
        _require(snapshot not in (None, c.c_void_p(-1).value), 'process-unavailable')
        try:
            item = _PROCESSENTRY32()
            item.size = c.sizeof(item)
            found = self.kernel.Process32FirstW(snapshot, c.byref(item))
            while found:
                if item.pid == pid:
                    return item.parentPid
                found = self.kernel.Process32NextW(snapshot, c.byref(item))
            raise WindowsLaunchError('process-unavailable')
        finally:
            self.kernel.CloseHandle(snapshot)

    def identity(self, process, pid, shell_pid):
        in_job = w.BOOL()
        _require(self.kernel.IsProcessInJob(process, None, c.byref(in_job)), 'identity-check-failed')
        length = w.UINT()
        package_status = self.kernel.GetPackageFullName(process, c.byref(length), None)
        _require(package_status in (0, 122, 15700), 'identity-check-failed')
        has_package = package_status != 15700
        creation, end, kernel, user = (w.FILETIME() for _ in range(4))
        _require(self.kernel.GetProcessTimes(process, *(c.byref(value) for value in (creation, end, kernel, user))), 'identity-check-failed')
        ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        created = datetime.fromtimestamp(ticks / 10**7 - 11644473600, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        parent = self.parent_pid(pid)
        session = self.session_id(pid)
        return dict(pid=pid, parentPid=parent, inJob=bool(in_job.value), hasPackageIdentity=has_package,
                    parentIsShell=parent == shell_pid,
                    isIndependent=not in_job.value and not has_package and parent == shell_pid,
                    createdAt=created, sessionId=session)


def inspect_process(pid: int | None = None) -> dict:
    """Read only allowlisted lifecycle facts, never image paths or package names.

    ``isIndependent`` describes a direct desktop child, not arbitrary descendants
    of a desktop child. Shell/identity queries that cannot be verified fail closed.
    """
    if pid is None:
        pid = os.getpid()
    if type(pid) is not int or not 0 < pid < 2**32:
        raise WindowsLaunchError('invalid-process-id')
    try:
        api = _WindowsAPI()
        shell_pid, shell = api.shell()
        process = None
        try:
            process = api.kernel.OpenProcess(0x1000, False, pid)
            _require(process, 'process-unavailable')
            return api.identity(process, pid, shell_pid)
        finally:
            if process:
                api.kernel.CloseHandle(process)
            api.kernel.CloseHandle(shell)
    except WindowsLaunchError:
        raise
    except (OSError, ValueError, TypeError, OverflowError):
        raise WindowsLaunchError('native-api-failed') from None


def _validate(command, environment, cwd):
    if not isinstance(command, list) or not command or len(command) > 256:
        raise WindowsLaunchError('invalid-command')
    if any(not isinstance(value, str) or '\0' in value for value in command):
        raise WindowsLaunchError('invalid-command')
    if not command[0] or not os.path.isabs(command[0]) or not Path(command[0]).is_file():
        raise WindowsLaunchError('invalid-command')
    line = subprocess.list2cmdline(command)
    if len(line) >= 32767:
        raise WindowsLaunchError('invalid-command')
    if environment is None:
        environment = dict(os.environ)
    if not isinstance(environment, dict):
        raise WindowsLaunchError('invalid-environment')
    for key, value in environment.items():
        if not isinstance(key, str) or not key or '=' in key or '\0' in key or not isinstance(value, str) or '\0' in value:
            raise WindowsLaunchError('invalid-environment')
    block = '\0'.join(f'{key}={value}' for key, value in sorted(environment.items(), key=lambda item: item[0].upper())) + '\0\0'
    if len(block) > 131072:
        raise WindowsLaunchError('invalid-environment')
    if cwd is None:
        cwd = os.path.dirname(command[0])
    if not isinstance(cwd, str) or '\0' in cwd or not os.path.isabs(cwd) or not Path(cwd).is_dir():
        raise WindowsLaunchError('invalid-cwd')
    return line, block, cwd


def launch_from_desktop(command: list[str], *, environment: dict | None = None,
                        cwd: str | None = None, hide: bool = True) -> dict:
    """Create a verified same-user desktop child, then resume its initial thread.

    Requires the interactive Windows Explorer shell and permission to use it as
    a process parent. There is deliberately no ordinary-spawn fallback. This
    does not elevate the child, change tokens, or modify machine security policy.
    Pass an explicit environment allowlist at product call sites. ``hide=False``
    leaves GUI startup visibility unchanged. All failures use enum-only messages.
    """
    api = None
    parent = None
    attributes = None
    initialized = False
    child = _PROCESS_INFORMATION()
    committed = False
    try:
        line, environment_block, cwd = _validate(command, environment, cwd)
        _require(type(hide) is bool, 'invalid-window-mode')
        api = _WindowsAPI()
        shell_pid, parent = api.shell(create=True)
        size = c.c_size_t()
        api.kernel.InitializeProcThreadAttributeList(None, 2, 0, c.byref(size))
        _require(0 < size.value <= 65536, 'launch-failed')
        attributes = c.create_string_buffer(size.value)
        _require(api.kernel.InitializeProcThreadAttributeList(attributes, 2, 0, c.byref(size)), 'launch-failed')
        initialized = True
        parent_value = w.HANDLE(parent)
        policy = w.DWORD(1)  # PROCESS_CREATION_DESKTOP_APP_BREAKAWAY_ENABLE_PROCESS_TREE
        _require(api.kernel.UpdateProcThreadAttribute(attributes, 0, 0x20000, c.byref(parent_value), c.sizeof(parent_value), None, None), 'launch-failed')
        _require(api.kernel.UpdateProcThreadAttribute(attributes, 0, 0x20012, c.byref(policy), c.sizeof(policy), None, None), 'launch-failed')
        startup = _STARTUPINFOEX()
        startup.startup.cb = c.sizeof(startup)
        startup.attributes = c.cast(attributes, c.c_void_p)
        if hide:
            startup.startup.flags = 1  # STARTF_USESHOWWINDOW
            startup.startup.show = 0  # SW_HIDE
        flags = 0x00080000 | 0x00000400 | 0x00000004  # extended info, Unicode env, suspended
        if hide:
            flags |= 0x08000000  # CREATE_NO_WINDOW; GUI apps still honor their own startup behavior.
        env = c.create_unicode_buffer(environment_block)
        command_line = c.create_unicode_buffer(line)
        _require(api.kernel.CreateProcessW(command[0], command_line, None, None, False, flags,
                                         env, cwd, c.byref(startup), c.byref(child)), 'launch-failed')
        identity = api.identity(child.process, child.pid, shell_pid)
        _require(identity['isIndependent'] and identity['sessionId'] == api.session_id(os.getpid()), 'identity-check-failed')
        _require(api.sid(child.process) == api.sid(parent), 'identity-check-failed')
        _require(api.kernel.ResumeThread(child.thread) == 1, 'resume-failed')
        committed = True
        return dict(pid=child.pid, isolation='desktop-independent', identity=identity)
    except WindowsLaunchError:
        raise
    except (OSError, ValueError, TypeError, OverflowError):
        raise WindowsLaunchError('native-api-failed') from None
    finally:
        if api is not None:
            if child.process and not committed:
                # Only this newly-created, still-suspended child is ours to stop.
                api.kernel.TerminateProcess(child.process, 1)
                api.kernel.WaitForSingleObject(child.process, 5000)
            if child.thread:
                api.kernel.CloseHandle(child.thread)
            if child.process:
                api.kernel.CloseHandle(child.process)
            if initialized:
                api.kernel.DeleteProcThreadAttributeList(attributes)
            if parent:
                api.kernel.CloseHandle(parent)

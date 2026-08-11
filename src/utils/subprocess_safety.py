from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
import signal
import stat
import subprocess
import sys
import threading
import time
from typing import Mapping, Sequence

from src.utils.sensitive_data import redact_sensitive_text


DEFAULT_SUBPROCESS_TIMEOUT_SECONDS = 300.0
DEFAULT_SUBPROCESS_OUTPUT_LIMIT_BYTES = 16 * 1024
_TRUNCATION_MARKER = b"\n...[output truncated]...\n"
_REDACTION_LOOKAHEAD_BYTES = 64 * 1024
_TRUNCATED_SECRET_PATTERNS = (
    (
        re.compile(r"(?i)\b((?:https?|ftp)://)[^/\s:@]+:[^/@\s]*\Z"),
        r"\1[REDACTED_USERINFO]@",
    ),
    (
        re.compile(r'(?i)("api[_-]?key"\s*:\s*")[^"]*\Z'),
        r"\1[REDACTED_API_KEY]",
    ),
    (
        re.compile(
            r'(?i)("[_-]?(?:[a-z0-9]+[_-])*[a-z0-9]*token"\s*:\s*")[^"]*\Z'
        ),
        r"\1[REDACTED_TOKEN]",
    ),
    (
        re.compile(r'(?i)("(?:password|client[_-]?secret)"\s*:\s*")[^"]*\Z'),
        r"\1[REDACTED_SECRET]",
    ),
)
_PIPE_DRAIN_JOIN_SECONDS = 2.0
_PROCESS_TREE_TERMINATION_SECONDS = 5.0
_WINDOWS_SUPERVISOR_SOURCE = """
import json
import subprocess
import sys

payload = json.loads(sys.stdin.buffer.read())
child = subprocess.Popen(
    payload["command"],
    cwd=payload["cwd"],
    env=payload["env"],
    stdin=subprocess.DEVNULL,
)
raise SystemExit(child.wait())
"""
_POSIX_FCHDIR_EXEC_SOURCE = """
import os
import sys

directory_fd = int(sys.argv[1])
command = sys.argv[2:]
if not command:
    raise SystemExit(127)
os.fchdir(directory_fd)
os.close(directory_fd)
os.execvp(command[0], command)
"""


class BoundedTextEmitter:
    def __init__(
        self,
        *,
        limit_bytes: int = DEFAULT_SUBPROCESS_OUTPUT_LIMIT_BYTES,
        path_prefixes: Mapping[str, object] | None = None,
    ) -> None:
        if limit_bytes <= len(_TRUNCATION_MARKER):
            raise ValueError("text output limit is too small")
        self.limit_bytes = int(limit_bytes)
        self.path_prefixes = dict(path_prefixes or {})
        self.emitted_bytes = 0
        self.truncated = False

    def filter(self, value: str) -> str:
        if self.truncated:
            return ""
        sanitized = redact_sensitive_text(value, path_prefixes=self.path_prefixes)
        encoded = sanitized.encode("utf-8", errors="replace")
        content_limit = self.limit_bytes - len(_TRUNCATION_MARKER)
        remaining_content = content_limit - self.emitted_bytes
        if len(encoded) <= remaining_content:
            self.emitted_bytes += len(encoded)
            return sanitized

        bounded = encoded[: max(0, remaining_content)] + _TRUNCATION_MARKER
        self.emitted_bytes += len(bounded)
        self.truncated = True
        return bounded.decode("utf-8", errors="ignore")


@dataclass
class _BoundedBytes:
    limit: int
    total: int = 0
    prefix: bytearray = field(default_factory=bytearray)
    suffix: bytearray = field(default_factory=bytearray)

    def append(self, chunk: bytes) -> None:
        if not chunk:
            return
        previous_total = self.total
        self.total += len(chunk)
        if self.total <= self.limit:
            self.prefix.extend(chunk)
            return
        prefix_limit = max(0, (self.limit - len(_TRUNCATION_MARKER)) // 2)
        suffix_limit = max(0, self.limit - len(_TRUNCATION_MARKER) - prefix_limit)
        if previous_total <= self.limit:
            combined = bytes(self.prefix) + chunk
            self.prefix = bytearray(combined[:prefix_limit])
            self.suffix = bytearray(combined[-suffix_limit:] if suffix_limit else b"")
            return
        if suffix_limit:
            self.suffix.extend(chunk)
            if len(self.suffix) > suffix_limit:
                del self.suffix[:-suffix_limit]

    def value(self) -> bytes:
        if self.total <= self.limit:
            return bytes(self.prefix)
        return bytes(self.prefix) + _TRUNCATION_MARKER + bytes(self.suffix)


@dataclass
class _RedactedBoundedBytes:
    limit: int
    path_prefixes: Mapping[str, object] | None = None
    total: int = 0
    raw_prefix: bytearray = field(default_factory=bytearray)

    @property
    def raw_limit(self) -> int:
        longest_path = max(
            (
                len(os.fsencode(os.fspath(prefix)))
                for prefix in (self.path_prefixes or {}).values()
                if isinstance(prefix, (str, bytes, os.PathLike))
            ),
            default=0,
        )
        return self.limit + max(_REDACTION_LOOKAHEAD_BYTES, longest_path + 256)

    def append(self, chunk: bytes) -> None:
        if not chunk:
            return
        self.total += len(chunk)
        remaining = self.raw_limit - len(self.raw_prefix)
        if remaining > 0:
            self.raw_prefix.extend(chunk[:remaining])

    def value(self) -> bytes:
        raw_truncated = self.total > len(self.raw_prefix)
        sanitized = redact_sensitive_text(
            bytes(self.raw_prefix).decode("utf-8", errors="replace"),
            path_prefixes=self.path_prefixes,
        )
        if raw_truncated:
            for pattern, replacement in _TRUNCATED_SECRET_PATTERNS:
                sanitized = pattern.sub(replacement, sanitized)
        encoded = sanitized.encode("utf-8", errors="replace")
        if raw_truncated:
            content_limit = max(0, self.limit - len(_TRUNCATION_MARKER))
            return encoded[:content_limit] + _TRUNCATION_MARKER
        capture = _BoundedBytes(limit=self.limit)
        capture.append(encoded)
        return capture.value()


def _decode_output(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _bounded_text(
    value,
    limit_bytes: int,
    *,
    path_prefixes: Mapping[str, object] | None = None,
) -> str:
    sanitized = redact_sensitive_text(
        _decode_output(value),
        path_prefixes=path_prefixes,
    )
    capture = _BoundedBytes(limit=max(1, int(limit_bytes)))
    capture.append(sanitized.encode("utf-8", errors="replace"))
    return capture.value().decode("utf-8", errors="replace")


def _drain_pipe(pipe, capture: _RedactedBoundedBytes) -> None:
    try:
        while True:
            chunk = pipe.read(8192)
            if not chunk:
                return
            capture.append(chunk)
    finally:
        pipe.close()


def _isolated_process_kwargs() -> dict[str, object]:
    if os.name == "nt":
        return {
            "creationflags": int(
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            )
        }
    return {"start_new_session": True}


class _WindowsKillOnCloseJob:
    def __init__(self, handle, kernel32) -> None:
        self._handle = handle
        self._kernel32 = kernel32

    def terminate(self) -> None:
        if self._handle:
            self._kernel32.TerminateJobObject(self._handle, 1)

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle:
            self._kernel32.CloseHandle(handle)


def _assign_windows_kill_on_close_job(
    process: subprocess.Popen,
) -> _WindowsKillOnCloseJob | None:
    if os.name != "nt":
        return None

    import ctypes
    from ctypes import wintypes

    class _IOCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IOCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        return None
    job = _WindowsKillOnCloseJob(handle, kernel32)
    information = _ExtendedLimitInformation()
    information.BasicLimitInformation.LimitFlags = 0x00002000
    if not kernel32.SetInformationJobObject(
        handle,
        9,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        job.close()
        return None
    process_handle = wintypes.HANDLE(int(process._handle))
    if not kernel32.AssignProcessToJobObject(handle, process_handle):
        job.close()
        return None
    return job


def bind_current_process_to_windows_kill_on_close_job(
) -> _WindowsKillOnCloseJob | None:
    """Bind this process, and therefore future children, to an owned Job."""
    if os.name != "nt":
        return None

    class _CurrentProcessHandle:
        # GetCurrentProcess returns the stable pseudo handle represented by -1.
        _handle = -1

    job = _assign_windows_kill_on_close_job(_CurrentProcessHandle())
    if job is None:
        raise RuntimeError("unable to establish Windows subprocess tree ownership")
    return job


def terminate_process_tree(
    process: subprocess.Popen,
    *,
    windows_job: _WindowsKillOnCloseJob | None = None,
) -> None:
    """Terminate a subprocess and descendants created in its isolated group."""
    if windows_job is not None:
        windows_job.terminate()
    elif os.name == "nt":
        creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=_PROCESS_TREE_TERMINATION_SECONDS,
                creationflags=creation_flags,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass

    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def _spawn_isolated_process(
    command: Sequence[str],
    *,
    cwd=None,
    env=None,
    working_directory_fd: int | None = None,
) -> tuple[subprocess.Popen, _WindowsKillOnCloseJob | None]:
    popen_kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        **_isolated_process_kwargs(),
    }
    if os.name != "nt":
        spawn_command = list(command)
        pass_fds: tuple[int, ...] = ()
        if working_directory_fd is not None:
            spawn_command = [
                sys.executable,
                "-c",
                _POSIX_FCHDIR_EXEC_SOURCE,
                str(working_directory_fd),
                *spawn_command,
            ]
            pass_fds = (working_directory_fd,)
        process = subprocess.Popen(
            spawn_command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            pass_fds=pass_fds,
            **popen_kwargs,
        )
        return process, None

    process = subprocess.Popen(
        [sys.executable, "-c", _WINDOWS_SUPERVISOR_SOURCE],
        stdin=subprocess.PIPE,
        **popen_kwargs,
    )
    windows_job = _assign_windows_kill_on_close_job(process)
    if windows_job is None:
        process.kill()
        process.wait(timeout=_PROCESS_TREE_TERMINATION_SECONDS)
        if process.stdin is not None:
            process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        raise RuntimeError("unable to establish Windows subprocess tree ownership")

    payload = json.dumps(
        {
            "command": list(command),
            "cwd": os.fspath(cwd) if cwd is not None else None,
            "env": dict(env) if env is not None else None,
        },
        ensure_ascii=True,
    ).encode("utf-8")
    assert process.stdin is not None
    try:
        process.stdin.write(payload)
        process.stdin.close()
    except BaseException:
        terminate_process_tree(process, windows_job=windows_job)
        windows_job.close()
        raise
    return process, windows_job


def _run_real_bounded_subprocess(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    output_limit_bytes: int,
    cwd=None,
    env=None,
    working_directory_fd: int | None = None,
    path_prefixes: Mapping[str, object] | None = None,
) -> subprocess.CompletedProcess[str]:
    process, windows_job = _spawn_isolated_process(
        command,
        cwd=cwd,
        env=env,
        working_directory_fd=working_directory_fd,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_capture = _RedactedBoundedBytes(
        limit=output_limit_bytes,
        path_prefixes=path_prefixes,
    )
    stderr_capture = _RedactedBoundedBytes(
        limit=output_limit_bytes,
        path_prefixes=path_prefixes,
    )
    stdout_thread = threading.Thread(
        target=_drain_pipe,
        args=(process.stdout, stdout_capture),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_drain_pipe,
        args=(process.stderr, stderr_capture),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    try:
        returncode = process.wait(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        returncode = process.poll()
        timed_out = True

    if not timed_out:
        for drain_thread in (stdout_thread, stderr_thread):
            drain_thread.join(timeout=max(0.0, deadline - time.monotonic()))
        timed_out = stdout_thread.is_alive() or stderr_thread.is_alive()

    if timed_out:
        terminate_process_tree(process, windows_job=windows_job)
        try:
            process.wait(timeout=_PROCESS_TREE_TERMINATION_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=_PROCESS_TREE_TERMINATION_SECONDS)
        stdout_thread.join(timeout=_PIPE_DRAIN_JOIN_SECONDS)
        stderr_thread.join(timeout=_PIPE_DRAIN_JOIN_SECONDS)
        if windows_job is not None:
            windows_job.close()
        raise subprocess.TimeoutExpired(
            list(command),
            timeout_seconds,
            output=stdout_capture.value(),
            stderr=stderr_capture.value(),
        ) from None
    if windows_job is not None:
        windows_job.close()
    return subprocess.CompletedProcess(
        args=list(command),
        returncode=returncode,
        stdout=stdout_capture.value().decode("utf-8", errors="replace"),
        stderr=stderr_capture.value().decode("utf-8", errors="replace"),
    )


def run_bounded_subprocess(
    command: Sequence[str],
    *,
    run_command=None,
    timeout_seconds: float = DEFAULT_SUBPROCESS_TIMEOUT_SECONDS,
    output_limit_bytes: int = DEFAULT_SUBPROCESS_OUTPUT_LIMIT_BYTES,
    cwd=None,
    env=None,
    working_directory_fd: int | None = None,
    path_prefixes: Mapping[str, object] | None = None,
) -> subprocess.CompletedProcess[str]:
    if timeout_seconds <= 0:
        raise ValueError("subprocess timeout must be positive")
    if output_limit_bytes <= len(_TRUNCATION_MARKER):
        raise ValueError("subprocess output limit is too small")
    if working_directory_fd is not None:
        if os.name == "nt":
            raise ValueError("working_directory_fd is only supported on POSIX")
        if cwd is not None:
            raise ValueError("cwd and working_directory_fd are mutually exclusive")
        descriptor_stat = os.fstat(working_directory_fd)
        if not stat.S_ISDIR(descriptor_stat.st_mode):
            raise ValueError("working_directory_fd must reference a directory")
    normalized_command = [str(part) for part in command]
    if run_command is None or run_command is subprocess.run:
        return _run_real_bounded_subprocess(
            normalized_command,
            timeout_seconds=timeout_seconds,
            output_limit_bytes=output_limit_bytes,
            cwd=cwd,
            env=env,
            working_directory_fd=working_directory_fd,
            path_prefixes=path_prefixes,
        )

    kwargs = {
        "check": False,
        "capture_output": True,
        "text": True,
        "timeout": timeout_seconds,
    }
    if cwd is not None:
        kwargs["cwd"] = cwd
    if env is not None:
        kwargs["env"] = env
    if working_directory_fd is not None:
        kwargs["working_directory_fd"] = working_directory_fd
    try:
        result = run_command(normalized_command, **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise subprocess.TimeoutExpired(
            exc.cmd,
            exc.timeout,
            output=_bounded_text(
                exc.output,
                output_limit_bytes,
                path_prefixes=path_prefixes,
            ),
            stderr=_bounded_text(
                exc.stderr,
                output_limit_bytes,
                path_prefixes=path_prefixes,
            ),
        ) from None
    return subprocess.CompletedProcess(
        args=normalized_command,
        returncode=int(result.returncode),
        stdout=_bounded_text(
            getattr(result, "stdout", ""),
            output_limit_bytes,
            path_prefixes=path_prefixes,
        ),
        stderr=_bounded_text(
            getattr(result, "stderr", ""),
            output_limit_bytes,
            path_prefixes=path_prefixes,
        ),
    )


def bounded_process_failure_detail(
    result: subprocess.CompletedProcess[str],
    *,
    path_prefixes: Mapping[str, object] | None = None,
) -> str:
    raw_detail = result.stderr or result.stdout or ""
    return redact_sensitive_text(raw_detail.strip(), path_prefixes=path_prefixes)

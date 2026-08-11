from __future__ import annotations

from dataclasses import dataclass, field
import subprocess
import threading
from typing import Mapping, Sequence

from src.utils.sensitive_data import redact_sensitive_text


DEFAULT_SUBPROCESS_TIMEOUT_SECONDS = 300.0
DEFAULT_SUBPROCESS_OUTPUT_LIMIT_BYTES = 16 * 1024
_TRUNCATION_MARKER = b"\n...[output truncated]...\n"


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


def _decode_output(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _bounded_text(value, limit_bytes: int) -> str:
    capture = _BoundedBytes(limit=max(1, int(limit_bytes)))
    capture.append(_decode_output(value).encode("utf-8", errors="replace"))
    return capture.value().decode("utf-8", errors="replace")


def _drain_pipe(pipe, capture: _BoundedBytes) -> None:
    try:
        while True:
            chunk = pipe.read(8192)
            if not chunk:
                return
            capture.append(chunk)
    finally:
        pipe.close()


def _run_real_bounded_subprocess(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    output_limit_bytes: int,
    cwd=None,
    env=None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_capture = _BoundedBytes(limit=output_limit_bytes)
    stderr_capture = _BoundedBytes(limit=output_limit_bytes)
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
    try:
        returncode = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        raise subprocess.TimeoutExpired(
            list(command),
            timeout_seconds,
            output=stdout_capture.value(),
            stderr=stderr_capture.value(),
        ) from None
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
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
) -> subprocess.CompletedProcess[str]:
    if timeout_seconds <= 0:
        raise ValueError("subprocess timeout must be positive")
    if output_limit_bytes <= len(_TRUNCATION_MARKER):
        raise ValueError("subprocess output limit is too small")
    normalized_command = [str(part) for part in command]
    if run_command is None or run_command is subprocess.run:
        return _run_real_bounded_subprocess(
            normalized_command,
            timeout_seconds=timeout_seconds,
            output_limit_bytes=output_limit_bytes,
            cwd=cwd,
            env=env,
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
    result = run_command(normalized_command, **kwargs)
    return subprocess.CompletedProcess(
        args=normalized_command,
        returncode=int(result.returncode),
        stdout=_bounded_text(getattr(result, "stdout", ""), output_limit_bytes),
        stderr=_bounded_text(getattr(result, "stderr", ""), output_limit_bytes),
    )


def bounded_process_failure_detail(
    result: subprocess.CompletedProcess[str],
    *,
    path_prefixes: Mapping[str, object] | None = None,
) -> str:
    raw_detail = result.stderr or result.stdout or ""
    return redact_sensitive_text(raw_detail.strip(), path_prefixes=path_prefixes)

import codecs
import os
import re
import sys
import threading
import weakref
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path


_LOG_REDACTION_FAILURE_TEXT = "[LOG_REDACTION_FAILED]"
_LOG_RECORD_TOO_LARGE_TEXT = "[LOG_RECORD_DROPPED]"
_MAX_LOG_RECORD_CHARS = 1024 * 1024
_RUNTIME_LOG_PATH_PREFIXES = {}
_ACTIVE_REDACTING_PIPE_LOGS = weakref.WeakSet()
_RUNTIME_LOG_PATH_PREFIXES_LOCK = threading.RLock()


def _normalize_runtime_log_path_prefixes(path_prefixes):
    if not isinstance(path_prefixes, Mapping):
        raise TypeError("path_prefixes must map stable labels to local path prefixes")

    normalized = {}
    for label, prefix in path_prefixes.items():
        if not isinstance(label, str) or not label:
            continue
        try:
            prefix_text = os.fspath(prefix)
        except TypeError:
            continue
        if isinstance(prefix_text, str) and prefix_text:
            normalized[label] = prefix_text
    return normalized


def register_runtime_log_path_prefixes(path_prefixes):
    """Add newly discovered private roots to current and future pipe logs."""

    normalized = _normalize_runtime_log_path_prefixes(path_prefixes)
    with _RUNTIME_LOG_PATH_PREFIXES_LOCK:
        _RUNTIME_LOG_PATH_PREFIXES.update(normalized)
        active_logs = tuple(_ACTIVE_REDACTING_PIPE_LOGS)
        for pipe_log in active_logs:
            pipe_log.add_path_prefixes(normalized)


def build_log_path_prefixes(
    *,
    project_root,
    runtime_paths,
    executable=None,
    user_home=None,
):
    """Build stable labels for private paths that may appear in runtime logs."""

    prefixes = {}

    def add(label, value):
        if value is None:
            return
        try:
            value_text = os.fspath(value)
        except TypeError:
            return
        if value_text:
            prefixes[label] = value_text

    add("<PROJECT_ROOT>", project_root)
    for runtime_key, label in (
        ("config_dir", "<CONFIG_DIR>"),
        ("history_dir", "<HISTORY_DIR>"),
        ("log_dir", "<LOG_DIR>"),
        ("plot_dir", "<PLOT_DIR>"),
        ("cache_dir", "<CACHE_DIR>"),
        ("runtime_dir", "<RUNTIME_DIR>"),
        ("migration_dir", "<MIGRATION_DIR>"),
        ("data_dir", "<DATA_DIR>"),
    ):
        add(label, runtime_paths.get(runtime_key))
    resolved_executable = Path(executable or sys.executable)
    add("<EXECUTABLE_DIR>", resolved_executable.parent)
    add("<USER_HOME>", user_home or Path.home())
    return prefixes


def _looks_like_windows_path(value):
    return bool(
        re.match(r"^[A-Za-z]:[\\/]", value)
        or value.startswith("\\\\")
        or "\\" in value
    )


def _path_prefix_pattern(prefix):
    normalized = str(prefix).rstrip("\\/")
    if not normalized:
        return None

    pieces = re.split(r"[\\/]", normalized)
    separator = r"[\\/]+"
    pattern = separator.join(re.escape(piece) for piece in pieces)
    windows_path = _looks_like_windows_path(normalized)
    flags = re.IGNORECASE if windows_path else 0
    left_boundary = r"(?<![\w])" if windows_path else ""
    diagnostic_boundary = r"(?=$|[\\/\s'\"\):,\]\};>]|[.!?](?=$|\s))"
    return re.compile(left_boundary + pattern + diagnostic_boundary, flags)


def _redact_path_prefixes(value, path_prefixes):
    if not path_prefixes:
        return value
    if not isinstance(path_prefixes, Mapping):
        raise TypeError("path_prefixes must map stable labels to local path prefixes")

    replacements = []
    for label, prefix in path_prefixes.items():
        if not isinstance(label, str) or not label:
            continue
        try:
            prefix_text = os.fspath(prefix)
        except TypeError:
            continue
        if not isinstance(prefix_text, str):
            continue
        pattern = _path_prefix_pattern(prefix_text)
        if pattern is not None:
            replacements.append((len(prefix_text.rstrip("\\/")), label, pattern))

    redacted = value
    for _length, label, pattern in sorted(
        replacements,
        key=lambda item: item[0],
        reverse=True,
    ):
        redacted = pattern.sub(lambda _match, replacement=label: replacement, redacted)
    return redacted


def redact_sensitive_text(value, *, path_prefixes=None):
    if not isinstance(value, str):
        return value

    redacted = re.sub(
        r"(?i)(authorization\s*:\s*(?:bearer|basic)\s+)[^\s,;'\"<>]+",
        r"\1[REDACTED_TOKEN]",
        value,
    )
    redacted = re.sub(
        r"(?i)\b((?:https?|ftp)://)[^/\s:@]+:[^/@\s]+@",
        r"\1[REDACTED_USERINFO]@",
        redacted,
    )
    redacted = re.sub(
        r"\b(gh(?:p|o|u|s|r)_)[A-Za-z0-9]{4,}",
        r"\1[REDACTED]",
        redacted,
    )
    redacted = re.sub(
        r"\b(github_pat_)[A-Za-z0-9_]{8,}",
        r"\1[REDACTED]",
        redacted,
    )
    redacted = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-[REDACTED]", redacted)
    redacted = re.sub(
        r'(?i)("api[_-]?key"\s*:\s*")[^"]{8,}(")',
        r"\1[REDACTED_API_KEY]\2",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(api[_-]?key\s*[:=]\s*)[A-Za-z0-9_\-]{16,}",
        r"\1[REDACTED_API_KEY]",
        redacted,
    )
    redacted = re.sub(
        r'(?i)("[_-]?(?:[a-z0-9]+[_-])*[a-z0-9]*token"\s*:\s*")[^"]*(")',
        r"\1[REDACTED_TOKEN]\2",
        redacted,
    )
    redacted = re.sub(
        r"(?i)((?<![a-z0-9_])[_-]?(?:[a-z0-9]+[_-])*[a-z0-9]*token\s*[:=]\s*)[^\s&;,\"'<>]+",
        r"\1[REDACTED_TOKEN]",
        redacted,
    )
    redacted = re.sub(
        r'(?i)("(?:password|client[_-]?secret)"\s*:\s*")[^"]*(")',
        r"\1[REDACTED_SECRET]\2",
        redacted,
    )
    redacted = re.sub(
        r"(?i)((?<![a-z0-9_])(?:password|client[_-]?secret)\s*[:=]\s*)[^\s&;,\"'<>]+",
        r"\1[REDACTED_SECRET]",
        redacted,
    )
    return _redact_path_prefixes(redacted, path_prefixes)


class RedactingTextStream:
    def __init__(
        self,
        stream,
        *,
        path_prefixes=None,
        redact_fn=redact_sensitive_text,
    ):
        self._stream = stream
        self._path_prefixes = dict(path_prefixes or {})
        self._redact_fn = redact_fn

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", None)

    @property
    def errors(self):
        return getattr(self._stream, "errors", None)

    def write(self, value):
        try:
            redacted = self._redact_fn(
                value,
                path_prefixes=self._path_prefixes,
            )
        except Exception:
            redacted = _LOG_REDACTION_FAILURE_TEXT
        return self._stream.write(redacted)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        return self._stream.flush()

    def fileno(self):
        return self._stream.fileno()

    def isatty(self):
        return self._stream.isatty()

    def __getattr__(self, name):
        return getattr(self._stream, name)


class RedactingPipeLog:
    """Persist stdout/stderr only after complete-record redaction.

    File descriptors 1 and 2 are redirected to pipes so low-level ``os.write``
    calls, native extensions, and inherited child-process output cannot bypass
    the redaction layer.  Each reader buffers through a newline before applying
    redaction, which keeps credentials and path prefixes intact when producers
    split one record across multiple writes.
    """

    def __init__(
        self,
        log_path,
        *,
        path_prefixes=None,
        redact_fn=redact_sensitive_text,
        max_record_chars=_MAX_LOG_RECORD_CHARS,
    ):
        self._stream = open(log_path, "a", encoding="utf-8", buffering=1)
        self._path_prefixes_lock = threading.Lock()
        with _RUNTIME_LOG_PATH_PREFIXES_LOCK:
            self._path_prefixes = dict(_RUNTIME_LOG_PATH_PREFIXES)
            self._path_prefixes.update(dict(path_prefixes or {}))
            _ACTIVE_REDACTING_PIPE_LOGS.add(self)
        self._redact_fn = redact_fn
        self._max_record_chars = max(1, int(max_record_chars))
        self._write_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._redirected = []
        self._captures = []
        self._closed = False

    def add_path_prefixes(self, path_prefixes):
        normalized = _normalize_runtime_log_path_prefixes(path_prefixes)
        with self._path_prefixes_lock:
            self._path_prefixes.update(normalized)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def redirect(self, fd, *, stream_name):
        read_fd, write_fd = os.pipe()
        try:
            os.dup2(write_fd, fd, inheritable=True)
        finally:
            if write_fd != fd:
                os.close(write_fd)

        text_stream = open(
            fd,
            "w",
            encoding="utf-8",
            errors="backslashreplace",
            buffering=1,
            closefd=False,
        )
        reader = threading.Thread(
            target=self._drain_pipe,
            args=(read_fd,),
            name=f"vantage-log-{stream_name}",
            daemon=True,
        )
        reader.start()
        self._redirected.append((fd, text_stream, reader))
        return text_stream

    @contextmanager
    def capture_subprocess_output(self, *, stream_name="subprocess"):
        """Return a binary pipe writer whose complete records are redacted."""

        if self._closed:
            raise RuntimeError("redacting pipe log is closed")
        read_fd, write_fd = os.pipe()
        writer = os.fdopen(write_fd, "wb", buffering=0)
        reader = threading.Thread(
            target=self._drain_pipe,
            args=(read_fd,),
            name=f"vantage-log-{stream_name}",
            daemon=True,
        )
        capture = (read_fd, writer, reader)
        self._captures.append(capture)
        reader.start()
        try:
            yield writer
        finally:
            self._finish_capture(capture)

    def write_record(self, value):
        if self._closed:
            raise RuntimeError("redacting pipe log is closed")
        self._persist(str(value))

    def _finish_capture(self, capture):
        read_fd, writer, reader = capture
        try:
            writer.close()
        except (OSError, ValueError):
            pass
        reader.join(timeout=5)
        if reader.is_alive():
            try:
                os.close(read_fd)
            except OSError:
                pass
            reader.join(timeout=1)
        try:
            self._captures.remove(capture)
        except ValueError:
            pass

    def _persist(self, value):
        with self._path_prefixes_lock:
            path_prefixes = dict(self._path_prefixes)
        try:
            redacted = self._redact_fn(
                value,
                path_prefixes=path_prefixes,
            )
        except Exception:
            redacted = _LOG_REDACTION_FAILURE_TEXT
            if value.endswith("\n"):
                redacted += "\n"
        with self._write_lock:
            self._stream.write(redacted)
            self._stream.flush()

    def _drain_pipe(self, read_fd):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        pending = ""
        dropping_oversized_record = False
        try:
            while True:
                chunk = os.read(read_fd, 8192)
                if not chunk:
                    pending += decoder.decode(b"", final=True)
                    break
                pending += decoder.decode(chunk)

                while True:
                    newline_index = pending.find("\n")
                    if newline_index < 0:
                        break
                    record = pending[: newline_index + 1]
                    pending = pending[newline_index + 1 :]
                    if dropping_oversized_record:
                        dropping_oversized_record = False
                    elif len(record) > self._max_record_chars:
                        self._persist(_LOG_RECORD_TOO_LARGE_TEXT + "\n")
                    else:
                        self._persist(record)

                if not dropping_oversized_record and len(pending) > self._max_record_chars:
                    self._persist(_LOG_RECORD_TOO_LARGE_TEXT + "\n")
                    pending = ""
                    dropping_oversized_record = True

            if pending and not dropping_oversized_record:
                if len(pending) > self._max_record_chars:
                    self._persist(_LOG_RECORD_TOO_LARGE_TEXT + "\n")
                else:
                    self._persist(pending)
        except OSError:
            if pending and not dropping_oversized_record:
                self._persist(pending)
        finally:
            try:
                os.close(read_fd)
            except OSError:
                pass

    def close(self):
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            with _RUNTIME_LOG_PATH_PREFIXES_LOCK:
                _ACTIVE_REDACTING_PIPE_LOGS.discard(self)

            redirected = list(self._redirected)
            captures = list(self._captures)
            for capture in captures:
                self._finish_capture(capture)
            for _fd, text_stream, _reader in redirected:
                try:
                    text_stream.flush()
                except (OSError, ValueError):
                    pass
                try:
                    text_stream.close()
                except (OSError, ValueError):
                    pass
            for fd, _text_stream, _reader in redirected:
                try:
                    os.close(fd)
                except OSError:
                    pass
            for _fd, _text_stream, reader in redirected:
                reader.join(timeout=5)

            with self._write_lock:
                try:
                    self._stream.flush()
                finally:
                    self._stream.close()

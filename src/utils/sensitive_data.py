import re
from collections.abc import Mapping
import os


_LOG_REDACTION_FAILURE_TEXT = "[LOG_REDACTION_FAILED]"


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
    flags = re.IGNORECASE if _looks_like_windows_path(normalized) else 0
    return re.compile(pattern + r"(?![A-Za-z0-9_])", flags)


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

    redacted = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-[REDACTED]", value)
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

import re


def redact_sensitive_text(value):
    if not isinstance(value, str):
        return value

    redacted = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-[REDACTED]", value)
    redacted = re.sub(
        r'(?i)("api[_-]?key"\s*:\s*")[^"]{8,}(")',
        r"\1[REDACTED_API_KEY]\2",
        redacted,
    )
    return re.sub(
        r"(?i)(api[_-]?key\s*[:=]\s*)[A-Za-z0-9_\-]{16,}",
        r"\1[REDACTED_API_KEY]",
        redacted,
    )

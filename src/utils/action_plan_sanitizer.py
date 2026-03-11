import re


ANALYSIS_SEPARATOR = "\n\n---ANALYSIS_END---\n\n"

_CORRUPT_LINE_PATTERNS = (
    re.compile(r"(?:<strong>-</strong>){2,}", re.IGNORECASE),
    re.compile(r"<b<br>>", re.IGNORECASE),
    re.compile(r"<b(?:<b)+<?b*", re.IGNORECASE),
    re.compile(r"</?stron<br>?", re.IGNORECASE),
)

_DROP_LINE_PATTERNS = (
    re.compile(r"^\|\s*$"),
    re.compile(r"^(?:\|\s*){2,}$"),
    re.compile(r"^#{2,}\s*\|\s*$"),
    re.compile(r"^(?:\*\s*){3,}$"),
    re.compile(r"^#{3,}\s*$"),
    re.compile(r"^(?:#{1,6}\s*){2,}$"),
    re.compile(r"^(?:\*\*\s*){2,}$"),
    re.compile(r"^(?:[-*+]\s*)+$"),
)


def _sanitize_line(line: str) -> str:
    sanitized = line.rstrip()
    for pattern in _CORRUPT_LINE_PATTERNS:
        sanitized = pattern.sub(" ", sanitized)
    sanitized = re.sub(r"<br\s*/?>", " ", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"</p>", " ", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"<p>", "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"<li>", "- ", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"</li>", " ", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"</?(ul|ol|strong|em)\b[^>]*>", "", sanitized, flags=re.IGNORECASE)
    sanitized = sanitized.replace("&nbsp;", " ")
    sanitized = re.sub(r"\s{2,}", " ", sanitized)
    stripped = sanitized.strip()
    if any(pattern.fullmatch(stripped) for pattern in _DROP_LINE_PATTERNS):
        return ""
    return sanitized.rstrip()


def _collapse_blank_lines(lines: list[str]) -> str:
    collapsed: list[str] = []
    blank_count = 0
    for line in lines:
        if not line.strip():
            blank_count += 1
            if blank_count > 2:
                continue
        else:
            blank_count = 0
        collapsed.append(line)
    return "\n".join(collapsed).strip()


def sanitize_action_plan_markdown(content: str) -> str:
    if not content:
        return ""

    normalized = content.replace("\r\n", "\n")
    if "---ANALYSIS_END---" in normalized:
        parts = [
            _collapse_blank_lines([_sanitize_line(line) for line in section.splitlines()])
            for section in normalized.split("---ANALYSIS_END---")
        ]
        return ANALYSIS_SEPARATOR.join(part for part in parts if part)

    return _collapse_blank_lines([_sanitize_line(line) for line in normalized.splitlines()])

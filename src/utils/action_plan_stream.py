import json


_VALID_SECTIONS = {"ANALYSIS", "PLAN"}
_VALID_EVENT_TYPES = {"thinking", "content", "error", "prompt", "system"}
_MAX_STREAM_CHUNK_CHARS = 12000


def emit_action_plan_stream_event(section: str, event_type: str, content: str, emit=print):
    normalized_section = section.strip().upper()
    normalized_event_type = event_type.strip().lower()

    if normalized_section not in _VALID_SECTIONS:
        raise ValueError(f"Unsupported action plan stream section: {section}")
    if normalized_event_type not in _VALID_EVENT_TYPES:
        raise ValueError(f"Unsupported action plan stream event type: {event_type}")

    text = content if isinstance(content, str) else str(content)
    chunks = [
        text[index:index + _MAX_STREAM_CHUNK_CHARS]
        for index in range(0, len(text), _MAX_STREAM_CHUNK_CHARS)
    ] or [""]

    for chunk in chunks:
        emit(f"STREAM_{normalized_section}_{normalized_event_type.upper()}:{json.dumps(chunk)}")


def build_action_plan_stream_printer(section: str, emit=print):
    normalized_section = section.strip().upper()
    if normalized_section not in _VALID_SECTIONS:
        raise ValueError(f"Unsupported action plan stream section: {section}")

    def callback(tag: str, content: str):
        if tag in _VALID_EVENT_TYPES:
            emit_action_plan_stream_event(normalized_section, tag, content, emit=emit)

    return callback

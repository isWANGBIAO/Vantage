import json


_VALID_SECTIONS = {"ANALYSIS", "PLAN"}


def build_action_plan_stream_printer(section: str, emit=print):
    normalized_section = section.strip().upper()
    if normalized_section not in _VALID_SECTIONS:
        raise ValueError(f"Unsupported action plan stream section: {section}")

    def callback(tag: str, content: str):
        if tag == "thinking":
            emit(f"STREAM_{normalized_section}_THINKING:{json.dumps(content)}")
        elif tag == "content":
            emit(f"STREAM_{normalized_section}_CONTENT:{json.dumps(content)}")
        elif tag == "error":
            emit(f"STREAM_{normalized_section}_ERROR:{json.dumps(content)}")

    return callback

"""Runtime logging, output redaction, and rate-limited diagnostics."""

import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

from src.core.config import Config
from src.utils.sensitive_data import build_log_path_prefixes, redact_sensitive_text

router = APIRouter()

def _build_runtime_log_path_prefixes():
    return build_log_path_prefixes(
        project_root=Config.get_project_root(),
        runtime_paths=Config.get_runtime_paths(),
    )

def _runtime_logs_root():
    logs_root = Path(Config.get_logs_dir())
    logs_root.mkdir(parents=True, exist_ok=True)
    return logs_root

def _runtime_log_pointer_path(channel):
    return _runtime_logs_root() / f"{channel}.latest.log"

def _create_runtime_log_path(channel, prefix, launched_at=None):
    launched_at = launched_at or datetime.now()
    logs_root = _runtime_logs_root()
    channel_dir = logs_root / channel
    channel_dir.mkdir(parents=True, exist_ok=True)
    log_path = channel_dir / f"{prefix}-{launched_at.strftime('%Y%m%d_%H%M%S')}.log"
    try:
        _runtime_log_pointer_path(channel).write_text(str(log_path.resolve()), encoding="utf-8")
    except OSError:
        pass
    return log_path

def _resolve_latest_runtime_log_path(channel):
    pointer_path = _runtime_log_pointer_path(channel)
    if pointer_path.exists():
        try:
            resolved = Path(pointer_path.read_text(encoding="utf-8").strip())
            if resolved.exists():
                return resolved
        except OSError:
            pass

    channel_dir = _runtime_logs_root() / channel
    if channel_dir.exists():
        candidates = sorted(channel_dir.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]

    return None

def _decode_subprocess_chunk(data):
    try:
        return data.decode("utf-8").rstrip()
    except Exception:
        return data.decode("gbk", errors="replace").rstrip()

def _log_subprocess_stderr_line(channel, line):
    message = (line or "").strip()
    if not message:
        return

    prefixed_message = f"[{channel}] {message}"
    if " - ERROR - " in message:
        logging.error(prefixed_message)
    elif " - WARNING - " in message:
        logging.warning(prefixed_message)
    else:
        logging.info(prefixed_message)

async def _drain_subprocess_stderr(stderr, channel, collected_lines):
    while True:
        line = await stderr.readline()
        if not line:
            break

        decoded = _decode_subprocess_chunk(line)
        redacted = redact_sensitive_text(decoded)
        if not redacted:
            continue

        collected_lines.append(redacted)
        _log_subprocess_stderr_line(channel, redacted)

_status_log_records = {}

_status_log_lock = threading.Lock()

def _rate_limited_status_log(key, message, *, interval_seconds, now_fn=None):
    now = (now_fn or time.monotonic)()
    with _status_log_lock:
        record = _status_log_records.get(key)
        if record is None or record.get("message") != message:
            _status_log_records[key] = {
                "message": message,
                "last_printed_at": now,
                "suppressed_count": 0,
            }
            print(message)
            return True

        elapsed = now - record["last_printed_at"]
        if elapsed < interval_seconds:
            record["suppressed_count"] += 1
            return False

        suppressed_count = record["suppressed_count"]
        record["last_printed_at"] = now
        record["suppressed_count"] = 0

    suffix = ""
    if suppressed_count:
        repeat_label = "repeat" if suppressed_count == 1 else "repeats"
        suffix = f" (suppressed {suppressed_count} {repeat_label})"
    print(f"{message}{suffix}")
    return True

def _reset_status_logs(prefix=None):
    with _status_log_lock:
        if prefix is None:
            _status_log_records.clear()
            return
        for key in list(_status_log_records):
            if isinstance(key, tuple) and key and key[0] == prefix:
                del _status_log_records[key]

def reset_camera_status_logs():
    _reset_status_logs("camera")

@router.get("/api/v1/system/logs")
async def get_system_logs():
    try:
        log_file = _resolve_latest_runtime_log_path("server")

        if log_file is None or not log_file.exists():
            return {"logs": ["Log file not found."]}

        with open(log_file, "r", encoding="utf-8", errors='ignore') as f:
            lines = f.readlines()

        return {"logs": lines[-200:]}
    except Exception as e:
        return {"logs": [f"Error reading logs: {str(e)}"]}

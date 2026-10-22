"""Stable photo identities with UTC offsets, while still reading legacy names."""

import re
from datetime import datetime
from pathlib import Path


def _aware_capture_time(captured_at):
    return captured_at if captured_at.tzinfo is not None else captured_at.astimezone()


def capture_minute_key(captured_at):
    return _aware_capture_time(captured_at).strftime("%Y%m%d%H%M%z")


def photo_filename(captured_at):
    return _aware_capture_time(captured_at).strftime("photo_%Y%m%d_%H%M%S_%z.jpg")


def parse_photo_capture_time(photo_path):
    name = Path(photo_path).name
    match = re.fullmatch(r"photo_(\d{8}_\d{6})(_[+-]\d{4})?\.jpg", name, re.IGNORECASE)
    if match is None:
        raise ValueError("Photo name has no supported capture timestamp")
    timestamp = match[1] + (match[2] or "")
    return datetime.strptime(timestamp, "%Y%m%d_%H%M%S_%z" if match[2] else "%Y%m%d_%H%M%S")

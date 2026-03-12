from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.person_detection import (
    PERSON_DETECTION_CONFIDENCE,
    PERSON_DETECTION_MODEL,
    detect_person_count,
    get_yolo_model,
)


TIMESTAMP_PATTERN = re.compile(r"(\d{8}_\d{6})")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def emit_status(message: str):
    print(message, flush=True)


def format_duration(seconds: float) -> str:
    if seconds >= 60:
        return f"{seconds / 60:.2f}m"
    return f"{seconds:.2f}s"


def build_progress_message(
    index: int,
    total_files: int,
    photos_with_people: int,
    photos_without_people: int,
    detection_rate: float,
    remaining_time: float,
    elapsed_time: float,
) -> str:
    remaining_files = total_files - index
    return (
        "Processed photos: "
        f"{index}/{total_files}, "
        f"with people: {photos_with_people}, "
        f"without people: {photos_without_people}, "
        f"remaining: {remaining_files}, "
        f"speed: {detection_rate:.2f} img/s, "
        f"eta: {format_duration(remaining_time)}, "
        f"elapsed: {format_duration(elapsed_time)}"
    )


def resolve_storage_paths(user_home: str | None = None, onedrive_env: str | None = None, ensure_exists: bool = True):
    explicit_user_home = user_home is not None
    user_home = user_home or os.path.expanduser("~")
    roots_to_check = []
    env_onedrive = onedrive_env
    if env_onedrive is None and not explicit_user_home:
        env_onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if env_onedrive:
        roots_to_check.append(env_onedrive)
    roots_to_check.append(os.path.join(user_home, "OneDrive"))

    checked_roots = []
    for root in roots_to_check:
        if root and root not in checked_roots:
            checked_roots.append(root)

    picture_dirs = ("Pictures", "图片")
    screenshot_dirs = ("Screenshots", "屏幕截图")
    photo_dir_name = "本机照片"

    for root in checked_roots:
        for picture_dir in picture_dirs:
            picture_root = Path(root) / picture_dir
            photo_dir = picture_root / photo_dir_name
            for screenshot_dir_name in screenshot_dirs:
                screenshot_dir = picture_root / screenshot_dir_name
                if photo_dir.exists() and screenshot_dir.exists():
                    return str(photo_dir), str(screenshot_dir)

    default_root = Path(checked_roots[0] if checked_roots else user_home) / "Pictures"
    photos_dir = default_root / photo_dir_name
    screenshots_dir = default_root / "Screenshots"
    if ensure_exists:
        photos_dir.mkdir(parents=True, exist_ok=True)
        screenshots_dir.mkdir(parents=True, exist_ok=True)
    return str(photos_dir), str(screenshots_dir)


def extract_timestamp(file_path: str) -> datetime | None:
    match = TIMESTAMP_PATTERN.search(Path(file_path).name)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")


def iter_image_files(root_dir: str):
    root = Path(root_dir)
    if not root.exists():
        return []
    return sorted(
        str(path)
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def get_candidate_screenshot_dirs(photo_time: datetime, screenshots_dir: str, hour_window: int = 1):
    screenshot_root = Path(screenshots_dir)
    candidate_dirs = []
    seen = set()

    for hour_offset in range(-hour_window, hour_window + 1):
        candidate_time = photo_time + timedelta(hours=hour_offset)
        candidate_dir = screenshot_root / candidate_time.strftime("%Y") / candidate_time.strftime("%m") / candidate_time.strftime("%d") / candidate_time.strftime("%H")
        candidate_dir_str = str(candidate_dir)
        if candidate_dir_str not in seen:
            seen.add(candidate_dir_str)
            candidate_dirs.append(candidate_dir_str)

    return candidate_dirs


def get_screenshots_within_time_range(photo_time: datetime, screenshots_dir: str, time_range_seconds: int = 2):
    screenshots = []
    seen_paths = set()
    for candidate_dir in get_candidate_screenshot_dirs(photo_time, screenshots_dir):
        for screenshot_path in iter_image_files(candidate_dir):
            screenshot_time = extract_timestamp(screenshot_path)
            if screenshot_time is None:
                continue
            if abs((screenshot_time - photo_time).total_seconds()) <= time_range_seconds:
                if screenshot_path not in seen_paths:
                    seen_paths.add(screenshot_path)
                    screenshots.append(screenshot_path)
    return screenshots


def collect_cleanup_targets(
    photos_dir: str,
    screenshots_dir: str,
    detect_person_fn,
    time_range_seconds: int = 2,
):
    cleanup_plan = []
    for photo_path in iter_image_files(photos_dir):
        person_count = detect_person_fn(photo_path)
        if person_count != 0:
            continue

        photo_time = extract_timestamp(photo_path)
        screenshot_paths = []
        if photo_time is not None:
            screenshot_paths = get_screenshots_within_time_range(
                photo_time,
                screenshots_dir,
                time_range_seconds=time_range_seconds,
            )

        cleanup_plan.append(
            {
                "photo_path": photo_path,
                "photo_time": photo_time,
                "screenshot_paths": screenshot_paths,
                "delete_paths": [photo_path, *screenshot_paths],
            }
        )
    return cleanup_plan


def apply_cleanup_plan(cleanup_plan):
    deleted_paths = []
    for entry in cleanup_plan:
        for file_path in entry["delete_paths"]:
            if os.path.exists(file_path):
                os.remove(file_path)
                deleted_paths.append(file_path)
    return deleted_paths


def detect(photos_dir: str, screenshots_dir: str, dry_run: bool = False, time_range_seconds: int = 2):
    all_files = iter_image_files(photos_dir)
    total_files = len(all_files)
    if total_files == 0:
        emit_status(f"No photos found under {photos_dir}")
        return []

    emit_status(
        f"Found {total_files} photos. Starting recheck with model "
        f"{PERSON_DETECTION_MODEL} (conf={PERSON_DETECTION_CONFIDENCE})..."
    )
    model = get_yolo_model()

    def detect_person_fn(photo_path: str) -> int:
        return detect_person_count(photo_path, model=model, conf=PERSON_DETECTION_CONFIDENCE)

    start_time = time.time()
    cleanup_plan = []
    photos_with_people = 0
    photos_without_people = 0

    for index, photo_path in enumerate(all_files, start=1):
        person_count = detect_person_fn(photo_path)
        if person_count == 0:
            photos_without_people += 1
            photo_time = extract_timestamp(photo_path)
            screenshot_paths = []
            if photo_time is not None:
                screenshot_paths = get_screenshots_within_time_range(
                    photo_time,
                    screenshots_dir,
                    time_range_seconds=time_range_seconds,
                )
            cleanup_plan.append(
                {
                    "photo_path": photo_path,
                    "photo_time": photo_time,
                    "screenshot_paths": screenshot_paths,
                    "delete_paths": [photo_path, *screenshot_paths],
                }
            )
            emit_status(f"No person detected: {photo_path}")
            for screenshot_path in screenshot_paths:
                emit_status(f"Related screenshot: {screenshot_path}")
        else:
            photos_with_people += 1

        elapsed_time = max(time.time() - start_time, 1e-6)
        remaining_files = total_files - index
        detection_rate = index / elapsed_time
        remaining_time = remaining_files / detection_rate if detection_rate else 0.0
        emit_status(
            build_progress_message(
                index=index,
                total_files=total_files,
                photos_with_people=photos_with_people,
                photos_without_people=photos_without_people,
                detection_rate=detection_rate,
                remaining_time=remaining_time,
                elapsed_time=elapsed_time,
            )
        )

    if dry_run:
        planned_deletions = sum(len(entry["delete_paths"]) for entry in cleanup_plan)
        emit_status(f"Dry run only. Planned deletions: {planned_deletions}")
        return cleanup_plan

    deleted_paths = apply_cleanup_plan(cleanup_plan)
    emit_status(f"Deleted files: {len(deleted_paths)}")
    return cleanup_plan


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Recheck historical photos and delete photo/screenshot pairs without people."
    )
    parser.add_argument("--photos-dir", help="Override the current photos directory.")
    parser.add_argument("--screenshots-dir", help="Override the current screenshots directory.")
    parser.add_argument("--time-range", type=int, default=2, help="Screenshot match window in seconds.")
    parser.add_argument("--dry-run", action="store_true", help="Only print the cleanup plan without deleting files.")
    return parser


def main():
    args = build_arg_parser().parse_args()
    default_photos_dir, default_screenshots_dir = resolve_storage_paths()
    photos_dir = args.photos_dir or default_photos_dir
    screenshots_dir = args.screenshots_dir or default_screenshots_dir
    emit_status(f"Photos dir: {photos_dir}")
    emit_status(f"Screenshots dir: {screenshots_dir}")
    detect(
        photos_dir=photos_dir,
        screenshots_dir=screenshots_dir,
        dry_run=args.dry_run,
        time_range_seconds=args.time_range,
    )


if __name__ == "__main__":
    main()

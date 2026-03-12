from __future__ import annotations

import argparse
import csv
import json
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
RESULT_CSV_HEADERS = [
    "photo_path",
    "status",
    "person_count",
    "error",
    "screenshot_paths",
    "processed_at",
]
DEFAULT_RESUME_FILE = Path("history") / "detect_cleanup_resume.json"
DEFAULT_RESULT_DIR = Path("output")


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
    photos_skipped: int = 0,
) -> str:
    remaining_files = total_files - index
    return (
        "Processed photos: "
        f"{index}/{total_files}, "
        f"with people: {photos_with_people}, "
        f"without people: {photos_without_people}, "
        f"skipped: {photos_skipped}, "
        f"remaining: {remaining_files}, "
        f"speed: {detection_rate:.2f} img/s, "
        f"eta: {format_duration(remaining_time)}, "
        f"elapsed: {format_duration(elapsed_time)}"
    )


def calculate_progress_metrics(index: int, total_files: int, start_index: int, start_time: float):
    elapsed_time = max(time.time() - start_time, 1e-6)
    processed_this_run = max(index - start_index, 1)
    remaining_files = total_files - index
    detection_rate = processed_this_run / elapsed_time
    remaining_time = remaining_files / detection_rate if detection_rate else 0.0
    return elapsed_time, detection_rate, remaining_time


def ensure_parent_dir(file_path: str | Path):
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)


def serialize_screenshot_paths(screenshot_paths):
    return "|".join(screenshot_paths)


def deserialize_screenshot_paths(raw_value: str):
    if not raw_value:
        return []
    return [item for item in raw_value.split("|") if item]


def initialize_result_csv(result_csv_path: str | Path, overwrite: bool = False):
    ensure_parent_dir(result_csv_path)
    result_csv = Path(result_csv_path)
    if result_csv.exists() and not overwrite:
        return
    with result_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=RESULT_CSV_HEADERS)
        writer.writeheader()


def append_result_row(
    result_csv_path: str | Path,
    photo_path: str,
    status: str,
    person_count: int | None = None,
    error: str = "",
    screenshot_paths: list[str] | None = None,
):
    initialize_result_csv(result_csv_path, overwrite=False)
    with Path(result_csv_path).open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=RESULT_CSV_HEADERS)
        writer.writerow(
            {
                "photo_path": photo_path,
                "status": status,
                "person_count": "" if person_count is None else str(person_count),
                "error": error,
                "screenshot_paths": serialize_screenshot_paths(screenshot_paths or []),
                "processed_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        fh.flush()


def load_cleanup_plan_from_csv(result_csv_path: str | Path):
    result_csv = Path(result_csv_path)
    if not result_csv.exists():
        return []

    cleanup_plan = []
    with result_csv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if row.get("status") != "no_person":
                continue
            photo_path = row.get("photo_path", "")
            screenshot_paths = deserialize_screenshot_paths(row.get("screenshot_paths", ""))
            cleanup_plan.append(
                {
                    "photo_path": photo_path,
                    "photo_time": extract_timestamp(photo_path),
                    "screenshot_paths": screenshot_paths,
                    "delete_paths": [photo_path, *screenshot_paths],
                }
            )
    return cleanup_plan


def build_default_result_csv_path():
    DEFAULT_RESULT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(DEFAULT_RESULT_DIR / f"detect_cleanup_{timestamp}.csv")


def load_resume_state(resume_file_path: str | Path):
    resume_file = Path(resume_file_path)
    if not resume_file.exists():
        return None
    with resume_file.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_resume_state(resume_file_path: str | Path, state):
    ensure_parent_dir(resume_file_path)
    with Path(resume_file_path).open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def find_resume_start_index(all_files: list[str], last_photo_path: str | None, processed_count: int):
    if last_photo_path:
        try:
            return all_files.index(last_photo_path) + 1
        except ValueError:
            pass
    return max(0, min(int(processed_count or 0), len(all_files)))


def is_resume_state_compatible(state, photos_dir: str, screenshots_dir: str, dry_run: bool, time_range_seconds: int):
    if not state:
        return False
    return (
        state.get("photos_dir") == photos_dir
        and state.get("screenshots_dir") == screenshots_dir
        and state.get("dry_run") == dry_run
        and int(state.get("time_range_seconds", -1)) == int(time_range_seconds)
        and state.get("model") == PERSON_DETECTION_MODEL
        and float(state.get("confidence", -1.0)) == float(PERSON_DETECTION_CONFIDENCE)
    )


def build_initial_resume_state(
    photos_dir: str,
    screenshots_dir: str,
    dry_run: bool,
    time_range_seconds: int,
    total_files: int,
    result_csv_path: str,
):
    return {
        "photos_dir": photos_dir,
        "screenshots_dir": screenshots_dir,
        "dry_run": dry_run,
        "time_range_seconds": time_range_seconds,
        "model": PERSON_DETECTION_MODEL,
        "confidence": PERSON_DETECTION_CONFIDENCE,
        "result_csv": result_csv_path,
        "processed_count": 0,
        "last_photo_path": "",
        "with_people": 0,
        "without_people": 0,
        "skipped": 0,
        "total_files": total_files,
        "completed": False,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def prepare_detect_run(
    all_files: list[str],
    photos_dir: str,
    screenshots_dir: str,
    dry_run: bool,
    time_range_seconds: int,
    result_csv_path: str | None = None,
    resume_file_path: str | None = None,
    reset_progress: bool = False,
):
    resume_file = str(Path(resume_file_path) if resume_file_path else DEFAULT_RESUME_FILE)
    total_files = len(all_files)

    if not reset_progress:
        existing_state = load_resume_state(resume_file)
        if (
            existing_state
            and not existing_state.get("completed", False)
            and is_resume_state_compatible(
                existing_state,
                photos_dir=photos_dir,
                screenshots_dir=screenshots_dir,
                dry_run=dry_run,
                time_range_seconds=time_range_seconds,
            )
        ):
            existing_result_csv = existing_state.get("result_csv")
            if existing_result_csv and Path(existing_result_csv).exists():
                start_index = find_resume_start_index(
                    all_files,
                    existing_state.get("last_photo_path"),
                    int(existing_state.get("processed_count", 0)),
                )
                existing_state["total_files"] = total_files
                existing_state["updated_at"] = datetime.now().isoformat(timespec="seconds")
                save_resume_state(resume_file, existing_state)
                emit_status(
                    f"Resuming recheck from {start_index}/{total_files}. Results CSV: {existing_result_csv}"
                )
                return existing_state, existing_result_csv, resume_file, start_index

    active_result_csv = result_csv_path or build_default_result_csv_path()
    initialize_result_csv(active_result_csv, overwrite=True)
    run_state = build_initial_resume_state(
        photos_dir=photos_dir,
        screenshots_dir=screenshots_dir,
        dry_run=dry_run,
        time_range_seconds=time_range_seconds,
        total_files=total_files,
        result_csv_path=active_result_csv,
    )
    save_resume_state(resume_file, run_state)
    emit_status(f"Starting new recheck. Results CSV: {active_result_csv}")
    return run_state, active_result_csv, resume_file, 0


def persist_progress(
    run_state,
    resume_file_path: str,
    photo_path: str,
    status: str,
):
    run_state["processed_count"] = int(run_state.get("processed_count", 0)) + 1
    run_state["last_photo_path"] = photo_path
    if status == "with_people":
        run_state["with_people"] = int(run_state.get("with_people", 0)) + 1
    elif status == "no_person":
        run_state["without_people"] = int(run_state.get("without_people", 0)) + 1
    elif status == "skipped":
        run_state["skipped"] = int(run_state.get("skipped", 0)) + 1
    run_state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_resume_state(resume_file_path, run_state)


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


def detect(
    photos_dir: str,
    screenshots_dir: str,
    dry_run: bool = False,
    time_range_seconds: int = 2,
    result_csv_path: str | None = None,
    resume_file_path: str | None = None,
    reset_progress: bool = False,
):
    photos_dir = os.path.abspath(photos_dir)
    screenshots_dir = os.path.abspath(screenshots_dir)
    all_files = iter_image_files(photos_dir)
    total_files = len(all_files)
    if total_files == 0:
        emit_status(f"No photos found under {photos_dir}")
        return []

    run_state, active_result_csv, active_resume_file, start_index = prepare_detect_run(
        all_files=all_files,
        photos_dir=photos_dir,
        screenshots_dir=screenshots_dir,
        dry_run=dry_run,
        time_range_seconds=time_range_seconds,
        result_csv_path=result_csv_path,
        resume_file_path=resume_file_path,
        reset_progress=reset_progress,
    )

    emit_status(
        f"Found {total_files} photos. Starting recheck with model "
        f"{PERSON_DETECTION_MODEL} (conf={PERSON_DETECTION_CONFIDENCE})..."
    )
    emit_status(f"Resume file: {active_resume_file}")
    emit_status(f"Results CSV: {active_result_csv}")
    model = get_yolo_model()

    def detect_person_fn(photo_path: str) -> int:
        return detect_person_count(photo_path, model=model, conf=PERSON_DETECTION_CONFIDENCE)

    start_time = time.time()
    photos_with_people = int(run_state.get("with_people", 0))
    photos_without_people = int(run_state.get("without_people", 0))
    photos_skipped = int(run_state.get("skipped", 0))

    for index, photo_path in enumerate(all_files[start_index:], start=start_index + 1):
        try:
            person_count = detect_person_fn(photo_path)
        except Exception as exc:
            append_result_row(
                active_result_csv,
                photo_path=photo_path,
                status="skipped",
                error=str(exc),
                screenshot_paths=[],
            )
            persist_progress(run_state, active_resume_file, photo_path, "skipped")
            photos_skipped = int(run_state.get("skipped", 0))
            emit_status(f"WARNING Image Read Error {photo_path}: {exc}")
            elapsed_time, detection_rate, remaining_time = calculate_progress_metrics(
                index=index,
                total_files=total_files,
                start_index=start_index,
                start_time=start_time,
            )
            emit_status(
                build_progress_message(
                    index=index,
                    total_files=total_files,
                    photos_with_people=photos_with_people,
                    photos_without_people=photos_without_people,
                    photos_skipped=photos_skipped,
                    detection_rate=detection_rate,
                    remaining_time=remaining_time,
                    elapsed_time=elapsed_time,
                )
            )
            continue

        if person_count == 0:
            photo_time = extract_timestamp(photo_path)
            screenshot_paths = []
            if photo_time is not None:
                screenshot_paths = get_screenshots_within_time_range(
                    photo_time,
                    screenshots_dir,
                    time_range_seconds=time_range_seconds,
                )
            append_result_row(
                active_result_csv,
                photo_path=photo_path,
                status="no_person",
                person_count=0,
                screenshot_paths=screenshot_paths,
            )
            persist_progress(run_state, active_resume_file, photo_path, "no_person")
            photos_without_people = int(run_state.get("without_people", 0))
            emit_status(f"No person detected: {photo_path}")
            for screenshot_path in screenshot_paths:
                emit_status(f"Related screenshot: {screenshot_path}")
        else:
            append_result_row(
                active_result_csv,
                photo_path=photo_path,
                status="with_people",
                person_count=person_count,
                screenshot_paths=[],
            )
            persist_progress(run_state, active_resume_file, photo_path, "with_people")
            photos_with_people = int(run_state.get("with_people", 0))

        elapsed_time, detection_rate, remaining_time = calculate_progress_metrics(
            index=index,
            total_files=total_files,
            start_index=start_index,
            start_time=start_time,
        )
        emit_status(
            build_progress_message(
                index=index,
                total_files=total_files,
                photos_with_people=photos_with_people,
                photos_without_people=photos_without_people,
                photos_skipped=photos_skipped,
                detection_rate=detection_rate,
                remaining_time=remaining_time,
                elapsed_time=elapsed_time,
            )
        )

    cleanup_plan = load_cleanup_plan_from_csv(active_result_csv)
    run_state["completed"] = True
    run_state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_resume_state(active_resume_file, run_state)

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
    parser.add_argument("--result-csv", help="Write scan results to this CSV path.")
    parser.add_argument("--resume-file", help="Write or load resume state from this JSON path.")
    parser.add_argument("--reset-progress", action="store_true", help="Ignore any unfinished resume state and start a new run.")
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
        result_csv_path=args.result_csv,
        resume_file_path=args.resume_file,
        reset_progress=args.reset_progress,
    )


if __name__ == "__main__":
    main()

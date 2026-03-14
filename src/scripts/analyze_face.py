import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from tqdm import tqdm

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from src.services.face_analysis_pipeline import (
    AnalysisConfig,
    FaceParser,
    MediaPipeFaceDetector,
    analyze_photo_file,
    build_face_report,
    discover_photo_search_paths,
    export_valid_results_to_excel,
    scan_photos,
)
from src.utils.face_analysis_db import (
    FACE_ANALYSIS_DB_FILE,
    clear_face_analysis_records,
    clear_face_progress_cache,
    clear_face_report_cache,
    initialize_face_analysis_storage,
    load_face_analysis_paths,
    load_face_analysis_records,
    save_face_progress_cache,
    upsert_face_analysis_record,
)
from src.utils.face_report_cache import save_face_report_cache


DB_FILE = FACE_ANALYSIS_DB_FILE
PLOT_OUTPUT_DIR = os.path.join("plot_outputs")
DEFAULT_MODEL_PATH = os.path.join("src", "scripts", "models", "face_parsing.farl.lapa.int8.onnx")


def update_progress(current, total, status="analyzing", current_file=""):
    save_face_progress_cache(
        {
            "current": current,
            "total": total,
            "percent": round((current / total) * 100, 2) if total > 0 else 0,
            "status": status,
            "current_file": current_file,
            "timestamp": datetime.now().timestamp(),
        },
        DB_FILE,
    )


def run_analysis(search_paths, model_path, db_file, output_dir, day=None, limit=None, rebuild=False):
    os.makedirs("history", exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    initialize_face_analysis_storage(db_file)

    config = AnalysisConfig()
    detector = MediaPipeFaceDetector(min_detection_confidence=config.min_detection_confidence)
    parser = FaceParser(model_path)

    photos = scan_photos(search_paths, day=day)
    if limit:
        photos = photos[-limit:]

    if rebuild:
        clear_face_analysis_records(db_file)
        clear_face_report_cache(db_file)
        clear_face_progress_cache(db_file)
        existing_paths = set()
    else:
        existing_paths = load_face_analysis_paths(db_file)

    photos_to_analyze = [photo for photo in photos if photo["path"] not in existing_paths]

    print(f"Scanning paths: {search_paths}")
    print(f"Found {len(photos)} photos.")
    print(f"Existing cached rows: {len(existing_paths)}")
    print(f"Remaining to analyze: {len(photos_to_analyze)}")

    total = len(photos_to_analyze)
    if total == 0:
        update_progress(1, 1, status="done")
    else:
        for index, photo in enumerate(
            tqdm(photos_to_analyze, total=total, desc="Analyzing face photos", unit="photo"),
            start=1,
        ):
            update_progress(index, total, current_file=os.path.basename(photo["path"]))
            record = analyze_photo_file(photo["path"], detector=detector, parser=parser, config=config)
            upsert_face_analysis_record(record, db_file)
        update_progress(total, total, status="done")

    analyzed_records = load_face_analysis_records(db_file)
    report = build_face_report(analyzed_records, output_dir)
    if report.get("count", 0) > 0:
        save_face_report_cache(report, db_file)
        print("REPORT_JSON:" + json.dumps(report, ensure_ascii=False))
    else:
        clear_face_report_cache(db_file)
        print("No valid face data found.")

    return analyzed_records, report


def export_excel(db_file):
    initialize_face_analysis_storage(db_file)
    records = load_face_analysis_records(db_file)
    if not records:
        return None

    output_path = os.path.abspath("Face_Analysis_History.xlsx")
    exported = export_valid_results_to_excel(records, output_path)
    return exported


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", action="store_true", help="Export cached results to Excel")
    parser.add_argument("--dir", nargs="+", help="Optional directories to scan")
    parser.add_argument("--day", help="Optional YYYYMMDD day filter for bounded analysis")
    parser.add_argument("--limit", type=int, help="Optional limit to the most recent N photos after filtering")
    parser.add_argument("--model", default=DEFAULT_MODEL_PATH, help="Face parsing ONNX model path")
    parser.add_argument("--rebuild", action="store_true", help="Ignore cached rows and rebuild the result set")
    args = parser.parse_args()

    search_paths = args.dir if args.dir else discover_photo_search_paths()
    if not search_paths:
        print("No photo directories found.")
        update_progress(1, 1, status="idle")
        return

    if args.export:
        exported = export_excel(DB_FILE)
        if exported is None:
            _, report = run_analysis(
                search_paths=search_paths,
                model_path=args.model,
                db_file=DB_FILE,
                output_dir=PLOT_OUTPUT_DIR,
                day=args.day,
                limit=args.limit,
                rebuild=args.rebuild,
            )
            if report.get("count", 0) == 0:
                print("Export skipped: no valid analyzed rows.")
                return
            exported = export_excel(DB_FILE)

        if exported:
            print(f"EXPORT_PATH:{exported}")
        else:
            print("Export skipped: no valid analyzed rows.")
        return

    run_analysis(
        search_paths=search_paths,
        model_path=args.model,
        db_file=DB_FILE,
        output_dir=PLOT_OUTPUT_DIR,
        day=args.day,
        limit=args.limit,
        rebuild=args.rebuild,
    )


if __name__ == "__main__":
    main()

"""Lazy face-analysis runtime, history reports, exports, and analysis routes."""

import asyncio
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse

from src.core.config import Config
from src.services.person_detection import (
    PRESENCE_DETECTION_CONFIDENCE,
    detect_foreground_presence_face_boxes,
    get_face_detector,
)
from src.utils.face_analysis_db import (
    clear_face_report_cache,
    initialize_face_analysis_storage,
    load_face_analysis_records,
    load_face_progress_cache,
    upsert_face_analysis_record,
)
from src.utils.face_report_cache import (
    build_face_report_response,
    load_face_report_cache,
    save_face_report_cache,
)
from src.utils.sensitive_data import RedactingPipeLog

from . import camera as _camera
from . import observability as _observability
from . import plots as _plots
from . import processes as _processes
from . import runtime as _runtime
from . import source_paths as _source_paths

router = APIRouter()

_face_analysis_pipeline_module = None

def get_face_analysis_pipeline_module():
    global _face_analysis_pipeline_module
    if _face_analysis_pipeline_module is None:
        from src.services import face_analysis_pipeline

        _face_analysis_pipeline_module = face_analysis_pipeline
    return _face_analysis_pipeline_module

FACE_ANALYSIS_MODEL_PATH = os.path.join("src", "scripts", "models", "face_parsing.farl.lapa.int8.onnx")

FACE_ANALYSIS_DB_FILE = None

PREWARM_FACE_ON_STARTUP = os.environ.get("VANTAGE_PREWARM_FACE_ON_STARTUP", "0") == "1"

PREWARM_FACE_DETECTION_ON_STARTUP = os.environ.get(
    "VANTAGE_PREWARM_FACE_DETECTION_ON_STARTUP",
    "0",
) == "1"

FACE_EXPORT_TIMEOUT_SECONDS = 60

_face_analysis_runtime = None

_face_analysis_runtime_lock = threading.Lock()

_face_report_refresh_lock = threading.Lock()

_face_analysis_job_lock = threading.Lock()

_face_analysis_job_running = False

def _get_face_analysis_db_file():
    if FACE_ANALYSIS_DB_FILE:
        return Path(FACE_ANALYSIS_DB_FILE)
    return Path(Config.get_history_dir()) / "face_analysis.db"

def get_face_analysis_runtime():
    global _face_analysis_runtime

    if _face_analysis_runtime is not None:
        return _face_analysis_runtime

    with _face_analysis_runtime_lock:
        if _face_analysis_runtime is None:
            pipeline = get_face_analysis_pipeline_module()
            config = pipeline.AnalysisConfig()
            detector = pipeline.MediaPipeFaceDetector(min_detection_confidence=config.min_detection_confidence)
            parser = pipeline.FaceParser(FACE_ANALYSIS_MODEL_PATH)
            _face_analysis_runtime = (detector, parser, config)

    return _face_analysis_runtime

def prewarm_runtime_models():
    if not PREWARM_FACE_ON_STARTUP:
        print("Face analysis runtime warmup deferred to first analysis request.")
    else:
        try:
            get_face_analysis_runtime()
            print("Face analysis runtime warmed up successfully.")
        except Exception as exc:
            print(f"Failed to warm face analysis runtime: {exc}")

    if not PREWARM_FACE_DETECTION_ON_STARTUP:
        print("Camera presence detector warmup deferred to background thread.")
        return

    try:
        import numpy as np

        face_detector = get_face_detector()
        blank_frame = np.zeros((640, 640, 3), dtype=np.uint8)
        detect_foreground_presence_face_boxes(
            blank_frame,
            model=face_detector,
            conf=PRESENCE_DETECTION_CONFIDENCE,
        )
        print("Camera face detector warmed up successfully.")
    except Exception as exc:
        print(f"Failed to warm camera face detector: {exc}")

def refresh_face_report_cache(db_file=None, output_dir=None):
    resolved_db_file = Path(db_file) if db_file else _get_face_analysis_db_file()
    resolved_output_dir = Path(output_dir) if output_dir else _plots._get_plot_dir()
    initialize_face_analysis_storage(resolved_db_file)
    with _face_report_refresh_lock:
        records = load_face_analysis_records(resolved_db_file)
        report = get_face_analysis_pipeline_module().build_face_report(records, resolved_output_dir)
        if report.get("count", 0) > 0:
            save_face_report_cache(report, resolved_db_file)
        else:
            clear_face_report_cache(resolved_db_file)
        return report

def process_captured_face_photo(photo_path):
    if not photo_path or not os.path.exists(photo_path):
        return False

    db_file = _get_face_analysis_db_file()
    plot_dir = _plots._get_plot_dir()
    initialize_face_analysis_storage(db_file)
    detector, parser, config = get_face_analysis_runtime()
    record = get_face_analysis_pipeline_module().analyze_photo_file(
        photo_path,
        detector=detector,
        parser=parser,
        config=config,
    )
    upsert_face_analysis_record(record, db_file)

    try:
        refresh_face_report_cache(db_file, plot_dir)
    except Exception as exc:
        print(f"Face report refresh failed for {photo_path}: {exc}")

    return True

@router.post("/api/v1/face/analyze")
async def analyze_face_history(background_tasks: BackgroundTasks):
    """Trigger background analysis of face history"""
    global _face_analysis_job_running

    with _face_analysis_job_lock:
        if _face_analysis_job_running:
            return JSONResponse(
                status_code=409,
                content={
                    "error": "Face analysis is already running",
                    "status": "running",
                },
            )
        _face_analysis_job_running = True

    current_dir = os.path.dirname(os.path.abspath(_source_paths.SERVER_FILE))
    script_path = os.path.join(current_dir, "scripts", "analyze_face.py")
    if not os.path.exists(script_path):
         script_path = os.path.abspath("src/scripts/analyze_face.py")

    def run_analysis():
        print("Starting face analysis...")
        try:
            log_path = _observability._create_runtime_log_path("face-analysis", "face-analysis")
            with RedactingPipeLog(
                log_path,
                path_prefixes=_observability._build_runtime_log_path_prefixes(),
            ) as log_file:
                log_file.write_record(
                    f"\n=== Face analysis launch {datetime.now().isoformat()} ===\n"
                )
                with log_file.capture_subprocess_output(
                    stream_name="face-analysis"
                ) as child_output:
                    subprocess.run(
                        [sys.executable, script_path],
                        check=True,
                        cwd=str(_processes._get_runtime_workdir()),
                        stdout=child_output,
                        stderr=subprocess.STDOUT,
                    )
            print("Face analysis complete.")
        except Exception as e:
            print(f"Face analysis failed: {e}")
        finally:
            global _face_analysis_job_running
            with _face_analysis_job_lock:
                _face_analysis_job_running = False

    background_tasks.add_task(run_analysis)
    return {"message": "Analysis started in background"}

@router.get("/api/v1/face/live")
async def get_face_live(active: bool = False):
    if active:
        _camera.mark_face_live_viewer_active()

    camera_online = _camera._camera_online()
    if not camera_online:
        return {
            "camera_online": False,
            "window_seconds": _camera.FACE_LIVE_WINDOW_SECONDS,
            "latest_score": None,
            "latest_datetime": "",
            "points": [],
        }

    points = _camera.snapshot_live_face_points()
    latest = points[-1] if points else None
    return {
        "camera_online": True,
        "window_seconds": _camera.FACE_LIVE_WINDOW_SECONDS,
        "latest_score": latest["score"] if latest else None,
        "latest_datetime": latest["datetime"] if latest else "",
        "points": points,
    }

@router.get("/api/v1/face/report")
async def get_face_report():
    """Get the latest analysis report including extremes and plot URL"""
    try:
        db_file = _get_face_analysis_db_file()
        initialize_face_analysis_storage(db_file)
        report_json = load_face_report_cache(db_file)
        if not report_json:
            return {"error": "No report generated"}

        return build_face_report_response(report_json, _runtime.state.photos_path)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/api/v1/face/export")
async def export_face_excel():
    """Export face analysis data to Excel"""
    try:
        current_dir = os.path.dirname(os.path.abspath(_source_paths.SERVER_FILE))
        script_path = os.path.join(current_dir, "scripts", "analyze_face.py")
        if not os.path.exists(script_path):
             script_path = os.path.abspath("src/scripts/analyze_face.py")

        def run_export_script():
            return subprocess.run(
                [sys.executable, script_path, "--export"],
                capture_output=True,
                cwd=str(_processes._get_runtime_workdir()),
                timeout=FACE_EXPORT_TIMEOUT_SECONDS,
            )

        try:
            proc = await asyncio.to_thread(run_export_script)
        except subprocess.TimeoutExpired:
            return JSONResponse(status_code=504, content={"error": "Export timed out"})

        def decode_output(value):
            if isinstance(value, str):
                return value
            if value is None:
                return ""
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                return value.decode("gbk", errors="replace")

        stdout_text = decode_output(proc.stdout)
        stderr_text = decode_output(proc.stderr)

        if proc.returncode != 0:
            return JSONResponse(status_code=500, content={"error": stderr_text})

        # The script should output the path to the excel file in stdout, e.g. "EXPORT_PATH:..."
        excel_path = None

        for line in stdout_text.splitlines():
            if line.startswith("EXPORT_PATH:"):
                excel_path = line.replace("EXPORT_PATH:", "").strip()
                break

        if excel_path and os.path.exists(excel_path):
            return FileResponse(excel_path, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', filename="Face_Analysis_History.xlsx")
        else:
             return JSONResponse(status_code=500, content={"error": "Export failed", "details": stdout_text or stderr_text})

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/api/v1/face/progress")
async def get_face_progress():
    """Get the current progress of face analysis"""
    try:
        db_file = _get_face_analysis_db_file()
        initialize_face_analysis_storage(db_file)
        data = load_face_progress_cache(db_file)

        if not data:
            return {"status": "idle", "percent": 0}

        # Check if stale (e.g. older than 1 minute)
        age_seconds = time.time() - data.get("timestamp", 0)
        if age_seconds > 60:
            with _face_analysis_job_lock:
                job_running = _face_analysis_job_running
            if job_running:
                stale_data = dict(data)
                if not stale_data.get("status") or stale_data.get("status") == "idle":
                    stale_data["status"] = "running"
                stale_data["stale"] = True
                stale_data["last_update_age_seconds"] = round(age_seconds, 1)
                return stale_data
            return {"status": "idle", "percent": 0}

        return data
    except Exception as e:
        return {"status": "error", "error": str(e)}

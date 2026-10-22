"""Lazy face-analysis runtime, history reports, exports, and analysis routes."""

import asyncio
import os
import subprocess
import threading
import time
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from src.core.config import Config
from src.core.user_config import load_settings
from src.services.face_local_runtime import configuration_status, profile_paths, get_local_runtime
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
    save_face_progress_cache,
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
_face_execution_lock = threading.RLock()

_face_analysis_job_running = False
_face_analysis_job_started_at = 0.0
_face_analysis_job_error = None

def _get_face_analysis_db_file():
    if FACE_ANALYSIS_DB_FILE:
        return Path(FACE_ANALYSIS_DB_FILE)
    return profile_paths()["db_file"]

def get_face_analysis_runtime():
    global _face_analysis_runtime

    profile_id = profile_paths()["profile_id"]
    if (_face_analysis_runtime is not None
            and getattr(_face_analysis_runtime[1], "paths", {}).get("profile_id") == profile_id):
        return _face_analysis_runtime

    with _face_analysis_runtime_lock:
        if (_face_analysis_runtime is None
                or getattr(_face_analysis_runtime[1], "paths", {}).get("profile_id") != profile_id):
            pipeline = get_face_analysis_pipeline_module()
            config = pipeline.AnalysisConfig()
            detector = pipeline.MediaPipeFaceDetector(min_detection_confidence=config.min_detection_confidence)
            parser = get_local_runtime()
            _face_analysis_runtime = (detector, parser, config)
            with _runtime.state.lock:
                _runtime.state.live_face_points.clear()
                _runtime.state.latest_live_face_score = None

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
    resolved_output_dir = Path(output_dir) if output_dir else _get_face_plot_dir()
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
    with _face_execution_lock:
        return _process_captured_face_photo(photo_path)


def _process_captured_face_photo(photo_path):
    if _face_analysis_job_running or not configuration_status()["ready"]:
        return False
    if not photo_path or not os.path.exists(photo_path):
        return False

    db_file = _get_face_analysis_db_file()
    plot_dir = _get_face_plot_dir()
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
    global _face_analysis_job_running, _face_analysis_job_started_at, _face_analysis_job_error

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
        _face_analysis_job_started_at = time.time()
        _face_analysis_job_error = None

    command, workdir = _processes._build_face_analysis_subprocess()

    def run_analysis():
        with _face_execution_lock:
            run_analysis_locked()

    def run_analysis_locked():
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
                    # Live sampling pauses during this job; release its model so
                    # history analysis cannot duplicate SAM3 GPU allocations.
                    if _face_analysis_runtime is not None:
                        parser = _face_analysis_runtime[1]
                        if getattr(parser, "is_external_local", False):
                            parser.close()
                    subprocess.run(
                        command,
                        check=True,
                        cwd=workdir,
                        stdout=child_output,
                        stderr=subprocess.STDOUT,
                    )
            print("Face analysis complete.")
        except Exception as e:
            print(f"Face analysis failed: {e}")
            global _face_analysis_job_error
            _face_analysis_job_error = "Face analysis failed. See System Logs for details."
            try:
                save_face_progress_cache({
                    "status": "error", "error": _face_analysis_job_error,
                    "percent": 0, "timestamp": time.time(),
                }, _get_face_analysis_db_file())
            except Exception:
                # Keep the in-memory error even if the disk itself failed.
                pass
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

    camera_online = _camera._camera_online() and _camera.has_fresh_camera_frame()
    if not camera_online:
        return {
            "camera_online": False,
            "window_seconds": _camera.FACE_LIVE_WINDOW_SECONDS,
            "latest_score": None,
            "latest_datetime": "",
            "points": [],
        }

    points = _camera.snapshot_live_face_points()
    selected_profile = profile_paths()["profile_id"]
    points = [point for point in points if point.get("profile_id") in (None, selected_profile)]
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
        meta = _local_report_metadata(db_file)
        if not report_json:
            return {"error": "No report generated", "local_analysis": meta}

        response = build_face_report_response(report_json, _runtime.state.photos_path)
        if not FACE_ANALYSIS_DB_FILE and report_json.get("trend_plot_path"):
            response["trend_plot"] = f'/api/v1/face/trend?profile_id={meta["profile_id"]}'
        return {**response, "local_analysis": meta}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})


def _local_report_metadata(db_file):
    status = configuration_status()
    paths = profile_paths()
    records = load_face_analysis_records(db_file)
    reasons = Counter(reason for row in records if not row.get("passed") for reason in row.get("fail_reason", []))
    latest = next((row for row in reversed(records) if row.get("passed")), {})
    meta = {**status, "skip_reason_counts": dict(reasons), "overlay_url": "",
            "latest_score": latest.get("score"), "latest_score_left": latest.get("score_left"),
            "latest_score_right": latest.get("score_right"), "latest_datetime": latest.get("datetime", ""),
            "provenance": "Local-only; brow/eye skin sampling; relative appearance, not medical severity."}
    try:
        overlay_meta = json.loads((paths["root"] / "overlay-meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        overlay_meta = {}
    if (paths["overlay"].is_file() and latest and
            overlay_meta.get("timestamp") == latest.get("timestamp") and
            overlay_meta.get("score") == latest.get("score")):
        meta["overlay_url"] = f'/api/v1/face/overlay?profile_id={paths["profile_id"]}&v={paths["overlay"].stat().st_mtime_ns}'
    return meta


@router.get("/api/v1/face/local-status")
async def get_face_local_status():
    status = configuration_status()
    if _face_analysis_runtime is not None:
        parser = _face_analysis_runtime[1]
        if getattr(parser, "paths", {}).get("profile_id") == status["profile_id"] and parser.last_error:
            return {**status, "ready": False, "message": parser.last_error}
    return status


@router.get("/api/v1/face/overlay")
async def get_face_overlay(profile_id: str = ""):
    paths = profile_paths()
    overlay = paths["overlay"]
    if profile_id != paths["profile_id"] or not overlay.is_file():
        raise HTTPException(status_code=404, detail="No sampling overlay for this profile.")
    return FileResponse(overlay, media_type="image/png", headers={"Cache-Control": "no-store"})


def _get_face_plot_dir():
    if FACE_ANALYSIS_DB_FILE:
        return _plots._get_plot_dir()
    return profile_paths()["root"] / "plots"


@router.get("/api/v1/face/trend")
async def get_face_trend(profile_id: str = ""):
    paths = profile_paths()
    plot = paths["root"] / "plots" / "dark_circles_trend.png"
    if profile_id != paths["profile_id"] or not plot.is_file():
        raise HTTPException(status_code=404, detail="No trend for this profile.")
    return FileResponse(plot, media_type="image/png", headers={"Cache-Control": "no-store"})

@router.get("/api/v1/face/export")
async def export_face_excel():
    """Export face analysis data to Excel"""
    try:
        command, workdir = _processes._build_face_analysis_subprocess(["--export"])

        def run_export_script():
            return subprocess.run(
                command,
                capture_output=True,
                cwd=workdir,
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
            export_file = Path(excel_path).resolve()
            export_root = (Path(Config.get_runtime_dir()) / "exports").resolve()
            cleanup = BackgroundTask(export_file.unlink, missing_ok=True) if (
                export_file.parent == export_root and export_file.name.startswith("Face_Analysis_History_")
            ) else None
            return FileResponse(excel_path, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', filename="Face_Analysis_History.xlsx", background=cleanup)
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

        with _face_analysis_job_lock:
            job_running = _face_analysis_job_running
            started_at = _face_analysis_job_started_at
            job_error = _face_analysis_job_error
        if job_error:
            return {"status": "error", "error": job_error, "percent": 0}
        if job_running and (not data or data.get("timestamp", 0) < started_at):
            return {"status": "queued", "percent": 0, "timestamp": started_at}
        if data and data.get("status") == "error":
            return data

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

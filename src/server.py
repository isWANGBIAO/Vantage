import os
import sys
import logging

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.append(current_dir)
if project_root not in sys.path:
    sys.path.append(project_root)

import cv2
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
import json
import hashlib
import time
import re
import subprocess
import threading
import glob
import asyncio
import math
import calendar
import tempfile
from collections import deque
from contextlib import suppress
from contextlib import asynccontextmanager
from datetime import datetime, date, timedelta
from pathlib import Path
from fastapi import FastAPI, WebSocket, Request, UploadFile, File, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import psutil
import shutil
import requests
import pandas as pd

from src.core.config import Config
from src.core.media_storage import get_media_paths_settings_file, resolve_media_storage_paths
from src.manager.manager_main import Monitor
from src.services.face_analysis_pipeline import (
    AnalysisConfig,
    FaceParser,
    MediaPipeFaceDetector,
    analyze_image_data,
    analyze_photo_file,
    build_face_report,
)
from src.services.llm_client import LLMClient
from src.services.model_call_recorder import (
    get_session_usage_summary,
    get_usage_dashboard_snapshot,
)
from src.services.person_detection import (
    PERSON_DETECTION_CONFIDENCE,
    PERSON_DETECTION_MODEL,
    get_yolo_model,
)
from cv2_enumerate_cameras import enumerate_cameras
from src.utils.data_loader import DataLoader

app = FastAPI()

RUN_PROMPT_BRIDGE_ARG = "--run-prompt"
PROJECT_ACTIVITY_SNAPSHOT_NAME = "project_activity.json"

FACE_ANALYSIS_MODEL_PATH = os.path.join("src", "scripts", "models", "face_parsing.farl.lapa.int8.onnx")
FACE_ANALYSIS_DB_FILE = None
FACE_REPORT_PLOT_OUTPUT_DIR = None
FACE_LIVE_WINDOW_SECONDS = 60
FACE_LIVE_SAMPLE_INTERVAL_SECONDS = 0.1
FACE_LIVE_IDLE_INTERVAL_SECONDS = 1.0
FACE_LIVE_VIEWER_TTL_SECONDS = 5.0
FACE_OVERLAY_BASE_SCORE_FONT_SCALE = 1.9
FACE_OVERLAY_SCORE_FONT_SCALE = FACE_OVERLAY_BASE_SCORE_FONT_SCALE * 2
FACE_OVERLAY_SCORE_THICKNESS = 8
FACE_OVERLAY_SCORE_PADDING = 24
FACE_OVERLAY_PERSON_FONT_SCALE = FACE_OVERLAY_BASE_SCORE_FONT_SCALE * 2
FACE_OVERLAY_PERSON_THICKNESS = 6
_face_analysis_runtime = None
_face_analysis_runtime_lock = threading.Lock()
_face_report_refresh_lock = threading.Lock()
_face_analysis_job_lock = threading.Lock()
_face_analysis_job_running = False


def _get_runtime_workdir():
    return Path(Config.get_project_root())


def _get_project_progress_root():
    configured_root = Path(Config.get_project_root())
    if (configured_root / "Prompt_Project_Management.md").exists():
        return configured_root

    current_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    return current_dir.parent


def _find_git_root(start_dir):
    current = Path(start_dir).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _decode_process_output(value):
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode("gbk", errors="replace")


def _load_project_activity_snapshot(project_root):
    snapshot_path = Path(project_root) / PROJECT_ACTIVITY_SNAPSHOT_NAME
    if not snapshot_path.exists():
        return []

    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Project activity snapshot parsing error: {exc}")
        return []

    commits = payload.get("commits", [])
    if not isinstance(commits, list):
        return []

    normalized_commits = []
    for commit in commits:
        if not isinstance(commit, dict):
            continue
        commit_hash = str(commit.get("hash", "")).strip()
        date_text = str(commit.get("date", "")).strip()
        message = str(commit.get("message", "")).strip()
        if commit_hash and date_text and message:
            normalized_commits.append({"hash": commit_hash, "date": date_text, "message": message})
    return normalized_commits


def _load_recent_git_commits(project_root, days=14):
    git_root = _find_git_root(project_root) or _find_git_root(Path.cwd())
    if git_root is None:
        return []

    recent_commits = []
    try:
        time_limit = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        git_cmd = ["git", "log", f'--since="{time_limit}"', "--pretty=format:%h|%ad|%s", "--date=short"]
        proc = subprocess.run(git_cmd, capture_output=True, cwd=git_root)

        if proc.returncode != 0 or not proc.stdout:
            return []

        out_text = _decode_process_output(proc.stdout)
        for line in out_text.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                recent_commits.append({
                    "hash": parts[0],
                    "date": parts[1],
                    "message": parts[2],
                })
    except Exception as e:
        print(f"Git log parsing error: {e}")

    return recent_commits


def _is_frozen_runtime():
    return bool(getattr(sys, "frozen", False))


def _resolve_run_prompt_script_path():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(current_dir, "scripts", "run_prompt.py")
    if not os.path.exists(script_path):
        script_path = os.path.abspath("src/scripts/run_prompt.py")
    return script_path


def _build_run_prompt_subprocess(run_prompt_args=None):
    resolved_args = list(run_prompt_args or [])
    if _is_frozen_runtime():
        return [sys.executable, RUN_PROMPT_BRIDGE_ARG, *resolved_args], str(_get_runtime_workdir())

    script_path = _resolve_run_prompt_script_path()
    return [sys.executable, script_path, *resolved_args], os.path.dirname(script_path)


def _get_face_analysis_db_file():
    if FACE_ANALYSIS_DB_FILE:
        return Path(FACE_ANALYSIS_DB_FILE)
    return Path(Config.get_history_dir()) / "face_analysis.db"


def _get_plot_dir():
    if FACE_REPORT_PLOT_OUTPUT_DIR:
        return Path(FACE_REPORT_PLOT_OUTPUT_DIR)
    return Path(Config.get_plot_dir())


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
        if not decoded:
            continue

        collected_lines.append(decoded)
        _log_subprocess_stderr_line(channel, decoded)

# Allow CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global State
class SystemState:
    def __init__(self):
        self.camera = None
        self.monitor = None
        self.latest_frame = None
        self.is_running = True
        self.background_thread_status = {
            "camera_loop": False,
            "face_live_loop": False,
            "initialize_latest_media_state": False,
            "monitor_loop": False,
            "update_legacy_storage_stats": False,
            "update_storage_stats": False,
            "yolo_loop": False,
        }
        self.lock = threading.Lock()
        self.paths = {'photo': None, 'screenshot': None}
        self.photos_path = None
        self.screenshots_path = None
        self.legacy_size = 0 # Cache for legacy storage size
        self.photos_size = 0  # Cache for photos storage size
        self.screenshots_size = 0  # Cache for screenshots storage size
        self.show_person_box = True
        self.person_boxes = []
        self.video_stream_client_count = 0
        self.live_face_points = deque()
        self.latest_live_face_score = None
        self.face_live_last_seen_at = 0.0
        self.last_processed_face_photo_path = None

state = SystemState()


def _mount_static_once(route_path, directory, name):
    if not directory or not os.path.exists(directory):
        return False

    normalized_directory = os.path.abspath(directory)
    for route in app.router.routes:
        if getattr(route, "path", None) != route_path:
            continue

        mounted_app = getattr(route, "app", None)
        current_directory = getattr(mounted_app, "directory", None)
        if current_directory is None or os.path.abspath(current_directory) != normalized_directory:
            route.app = StaticFiles(directory=directory)
            return False

        return False

    app.mount(route_path, StaticFiles(directory=directory), name=name)
    return True


def _start_background_thread_once(thread_name, target):
    if state.background_thread_status.get(thread_name):
        return False

    threading.Thread(target=target, daemon=True).start()
    state.background_thread_status[thread_name] = True
    return True


def get_face_analysis_runtime():
    global _face_analysis_runtime

    if _face_analysis_runtime is not None:
        return _face_analysis_runtime

    with _face_analysis_runtime_lock:
        if _face_analysis_runtime is None:
            config = AnalysisConfig()
            detector = MediaPipeFaceDetector(min_detection_confidence=config.min_detection_confidence)
            parser = FaceParser(FACE_ANALYSIS_MODEL_PATH)
            _face_analysis_runtime = (detector, parser, config)

    return _face_analysis_runtime


def prewarm_runtime_models():
    try:
        get_face_analysis_runtime()
        print("Face analysis runtime warmed up successfully.")
    except Exception as exc:
        print(f"Failed to warm face analysis runtime: {exc}")

    try:
        get_yolo_model()
        print("YOLO model warmed up successfully.")
    except Exception as exc:
        print(f"Failed to warm YOLO model: {exc}")


def _camera_online():
    camera = state.camera
    return bool(camera and camera.isOpened())


def _ensure_live_face_points_deque():
    if not isinstance(state.live_face_points, deque):
        state.live_face_points = deque(state.live_face_points)


def _prune_live_face_points(now_ts=None):
    _ensure_live_face_points_deque()
    now_ts = float(now_ts if now_ts is not None else time.time())
    cutoff = now_ts - FACE_LIVE_WINDOW_SECONDS
    while state.live_face_points and state.live_face_points[0]["timestamp"] < cutoff:
        state.live_face_points.popleft()


def store_live_face_result(result):
    if not result or not result.get("passed") or result.get("score") is None:
        return

    with state.lock:
        _ensure_live_face_points_deque()
        state.live_face_points.append(
            {
                "timestamp": float(result["timestamp"]),
                "datetime": result["datetime"],
                "score": float(result["score"]),
            }
        )
        _prune_live_face_points(result["timestamp"])


def snapshot_live_face_points(now_ts=None):
    with state.lock:
        _prune_live_face_points(now_ts)
        return list(state.live_face_points)


def update_live_face_overlay_state(result):
    latest_score = None
    if result and result.get("passed") and result.get("score") is not None:
        latest_score = float(result["score"])

    with state.lock:
        state.latest_live_face_score = latest_score


def format_live_face_score_label(score):
    if score is None or not math.isfinite(float(score)):
        return "Dark Circle Score: --"
    return f"Dark Circle Score: {float(score):.2f}"


def mark_face_live_viewer_active(now_ts=None):
    state.face_live_last_seen_at = now_ts if now_ts is not None else time.time()


def has_active_face_live_viewer(now_ts=None):
    now_ts = now_ts if now_ts is not None else time.time()
    last_seen_at = getattr(state, "face_live_last_seen_at", 0.0) or 0.0
    return (now_ts - last_seen_at) <= FACE_LIVE_VIEWER_TTL_SECONDS


def register_video_stream_client():
    with state.lock:
        state.video_stream_client_count = max(0, getattr(state, "video_stream_client_count", 0)) + 1


def unregister_video_stream_client():
    with state.lock:
        state.video_stream_client_count = max(0, getattr(state, "video_stream_client_count", 0) - 1)


def has_active_video_stream_client():
    with state.lock:
        return getattr(state, "video_stream_client_count", 0) > 0


def should_run_yolo_detection():
    return bool(state.show_person_box and has_active_video_stream_client())


def refresh_face_report_cache(db_file=None, output_dir=None):
    resolved_db_file = Path(db_file) if db_file else _get_face_analysis_db_file()
    resolved_output_dir = Path(output_dir) if output_dir else _get_plot_dir()
    initialize_face_analysis_storage(resolved_db_file)
    with _face_report_refresh_lock:
        records = load_face_analysis_records(resolved_db_file)
        report = build_face_report(records, resolved_output_dir)
        if report.get("count", 0) > 0:
            save_face_report_cache(report, resolved_db_file)
        else:
            clear_face_report_cache(resolved_db_file)
        return report


def process_captured_face_photo(photo_path):
    if not photo_path or not os.path.exists(photo_path):
        return False

    db_file = _get_face_analysis_db_file()
    plot_dir = _get_plot_dir()
    initialize_face_analysis_storage(db_file)
    detector, parser, config = get_face_analysis_runtime()
    record = analyze_photo_file(photo_path, detector=detector, parser=parser, config=config)
    upsert_face_analysis_record(record, db_file)

    try:
        refresh_face_report_cache(db_file, plot_dir)
    except Exception as exc:
        print(f"Face report refresh failed for {photo_path}: {exc}")

    return True

def update_legacy_storage_stats():
    """Background task to calculate legacy storage usage once to avoid blocking main loop"""
    print("Starting background legacy storage scan...")
    try:
        total_size = 0
        
        # Candidates for legacy paths (OneDrive)
        candidates = []
        onedrive_env = os.environ.get("OneDrive")
        user_home = os.path.expanduser("~")
        
        roots_to_check = []
        if onedrive_env:
            roots_to_check.append(onedrive_env)
        roots_to_check.append(os.path.join(user_home, "OneDrive"))
        
        # STRICT SUBDIRECTORIES: Only folders created by THIS program
        subdirs = [
             os.path.join("Pictures", "本机照片"),
             os.path.join("图片", "本机照片"),
             os.path.join("Pictures", "Screenshots"),
             os.path.join("图片", "屏幕截图"),
             "本机照片", 
             os.path.join("Pictures", "屏幕截图"),
             os.path.join("图片", "Screenshots")
        ]
        
        for root_dir in set(roots_to_check): # unique roots
            if root_dir and os.path.exists(root_dir):
                for sub in subdirs:
                    candidates.append(os.path.join(root_dir, sub))

        # Filter out invalid or current paths
        checked_paths = set()
        for cand in candidates:
            if not os.path.exists(cand): continue
            
            # Skip if current path
            if state.photos_path and os.path.abspath(cand) == os.path.abspath(state.photos_path): continue
            if state.screenshots_path and os.path.abspath(cand) == os.path.abspath(state.screenshots_path): continue
            
            # Avoid duplicates
            abs_cand = os.path.abspath(cand)
            if abs_cand in checked_paths: continue
            checked_paths.add(abs_cand)
            
            print(f"Scanning legacy path: {abs_cand}")
            for root, dirs, files in os.walk(cand):
                total_size += sum(os.path.getsize(os.path.join(root, f)) for f in files)
        
        state.legacy_size = total_size
        print(f"Legacy storage scan complete: {state.legacy_size / (1024**2):.2f} MB")
        
    except Exception as e:
        print(f"Legacy storage scan error: {e}")

def update_storage_stats():
    """Background thread to periodically update photos/screenshots storage size cache."""
    while state.is_running:
        try:
            photos_size = 0
            if state.photos_path and os.path.exists(state.photos_path):
                for root, dirs, files in os.walk(state.photos_path):
                    photos_size += sum(os.path.getsize(os.path.join(root, f)) for f in files)
            state.photos_size = photos_size

            screenshots_size = 0
            if state.screenshots_path and os.path.exists(state.screenshots_path):
                for root, dirs, files in os.walk(state.screenshots_path):
                    screenshots_size += sum(os.path.getsize(os.path.join(root, f)) for f in files)
            state.screenshots_size = screenshots_size
        except Exception as e:
            print(f"Storage stats update error: {e}")
        time.sleep(60)  # Update every 60 seconds

# Balance Sheet helpers
def _normalize_cell_value(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value

def _looks_like_date(text):
    if not isinstance(text, str):
        return False
    s = text.strip()
    if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$", s):
        return True
    if re.match(r"^\d{4}年\d{1,2}月\d{1,2}日$", s):
        return True
    return False

def _coerce_number(value):
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s or _looks_like_date(s):
            return None
        cleaned = re.sub(r"[^\d\.\-]", "", s)
        if cleaned in ("", "-", "."):
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None

def _find_latest_date_in_df(df):
    if df is None or df.empty:
        return None
    preferred = [col for col in df.columns if any(k in str(col) for k in ["日期", "时间", "Date", "date", "Time", "time"])]
    fallback = [col for col in df.columns if "月份" in str(col)]
    for col in preferred + fallback:
        try:
            series = pd.to_datetime(df[col], errors="coerce")
        except Exception:
            continue
        if series.notna().any():
            latest = series.max()
            if pd.notna(latest):
                return latest.date()
    return None

def _find_date_column(df):
    if df is None or df.empty:
        return None

    preferred = [
        col
        for col in df.columns
        if any(k in str(col) for k in ["日期", "时间", "Date", "date", "Time", "time", "月份"])
    ]

    for col in preferred:
        try:
            series = pd.to_datetime(df[col], errors="coerce")
        except Exception:
            continue
        if series.notna().any():
            return col

    for col in df.columns:
        try:
            series = pd.to_datetime(df[col], errors="coerce")
        except Exception:
            continue
        if series.notna().sum() >= max(3, min(10, len(df))):
            return col

    return None

def _find_metric_from_columns(df, keywords):
    if df is None or df.empty:
        return None
    for col in df.columns:
        col_name = str(col)
        if any(k in col_name for k in keywords):
            values = []
            for v in df[col].tolist():
                num = _coerce_number(v)
                if num is not None:
                    values.append(num)
            if values:
                return {"value": values[-1], "field": col_name}
    return None

def _find_metric_from_rows(df, keywords):
    if df is None or df.empty:
        return None
    for _, row in df.iterrows():
        label_cell = None
        for cell in row.tolist():
            if isinstance(cell, str) and any(k in cell for k in keywords):
                label_cell = cell
                break
        if label_cell is None:
            continue
        # Prefer numeric values from right to left (often latest column)
        row_values = row.tolist()
        for col, cell in zip(reversed(df.columns), reversed(row_values)):
            num = _coerce_number(cell)
            if num is not None:
                return {"value": num, "field": str(col), "label": label_cell}
    return None

def _find_metric(sheets, keywords):
    for sheet_name, df in sheets.items():
        result = _find_metric_from_columns(df, keywords)
        if result:
            result["sheet"] = sheet_name
            return result
    for sheet_name, df in sheets.items():
        result = _find_metric_from_rows(df, keywords)
        if result:
            result["sheet"] = sheet_name
            return result
    return None

def _find_budget_sheet(sheets):
    if not sheets:
        return None, None
    for sheet_name, df in sheets.items():
        if str(sheet_name).strip().lower() == "budget":
            return sheet_name, df
    for sheet_name, df in sheets.items():
        name = str(sheet_name)
        if "预算" in name or "Budget" in name:
            return sheet_name, df
    for sheet_name, df in sheets.items():
        cols = [str(c) for c in df.columns]
        if any("是否必须" in c or "必需" in c for c in cols) and any("月" in c or "年" in c or "日" in c for c in cols):
            return sheet_name, df
    return None, None

def _parse_required_flag(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if any(k in text for k in ["必须", "必需", "是", "yes", "YES", "Yes", "Y", "y"]):
        return True
    if any(k in text for k in ["非必须", "不必须", "否", "no", "NO", "No", "N", "n"]):
        return False
    return None

def _find_first_column(columns_or_df, keywords):
    columns = None
    if hasattr(columns_or_df, "columns"):
        columns = columns_or_df.columns
    else:
        columns = columns_or_df

    keyword_texts = [str(keyword) for keyword in keywords if keyword is not None]

    for col in columns:
        name = str(col)
        if any(name == keyword for keyword in keyword_texts):
            return col

    for col in columns:
        name = str(col)
        if any(keyword in name for keyword in keyword_texts):
            return col
    return None

def _find_expense_sheet(sheets):
    if not sheets:
        return None, None

    for sheet_name, df in sheets.items():
        normalized_name = str(sheet_name).strip().lower()
        if normalized_name == "expense":
            return sheet_name, df

    for sheet_name, df in sheets.items():
        name = str(sheet_name)
        if "开销" in name or "Expense" in name or "expense" in name:
            return sheet_name, df

    for sheet_name, df in sheets.items():
        date_col = _find_date_column(df)
        balance_col = _find_first_column(df, ["现金及现金等价物+股票", "现金及现金等价物", "现金", "股票"])
        daily_average_col = _find_first_column(df, ["日均支出", "日均开销", "日均成本"])
        period_spend_col = _find_first_column(df, ["期间支出", "支出"])

        if date_col is not None and any(col is not None for col in [balance_col, daily_average_col, period_spend_col]):
            return sheet_name, df

    return None, None

def _compute_monthly_from_row(row, days_in_month):
    month_col = _find_first_column(row.index, ["每月", "月消费", "月支出", "月开销", "月均", "月度"])
    year_col = _find_first_column(row.index, ["一年合计", "年消费", "年支出", "年开销", "年均", "年费", "年"])
    day_col = _find_first_column(row.index, ["每日", "日消费", "日支出", "日开销", "日均"])

    value = None
    if month_col is not None:
        value = _coerce_number(row.get(month_col))
    if value is None and year_col is not None:
        year_value = _coerce_number(row.get(year_col))
        if year_value is not None:
            value = year_value / 12.0
    if value is None and day_col is not None:
        day_value = _coerce_number(row.get(day_col))
        if day_value is not None and days_in_month:
            value = day_value * days_in_month
    return value, month_col or year_col or day_col

def _build_budget_summary(sheets):
    sheet_name, df = _find_budget_sheet(sheets)
    if df is None or df.empty:
        return None

    today = datetime.now()
    days_in_month = calendar.monthrange(today.year, today.month)[1]

    required_col = _find_first_column(df, ["是否必须", "必需", "是否必需"])

    monthly_required = 0.0
    monthly_optional = 0.0
    required_count = 0
    optional_count = 0
    source_col = None

    for _, row in df.iterrows():
        flag = _parse_required_flag(row.get(required_col)) if required_col else None
        monthly_value, value_col = _compute_monthly_from_row(row, days_in_month)
        if monthly_value is None:
            continue
        if source_col is None and value_col is not None:
            source_col = str(value_col)
        if flag is True:
            monthly_required += monthly_value
            required_count += 1
        elif flag is False:
            monthly_optional += monthly_value
            optional_count += 1

    return {
        "sheet": sheet_name,
        "monthly_required": monthly_required if required_count else None,
        "monthly_optional": monthly_optional if optional_count else None,
        "required_count": required_count,
        "optional_count": optional_count,
        "source_column": source_col
    }

def _sheet_to_payload(df, max_rows=200):
    if df is None:
        return {"columns": [], "rows": [], "row_count": 0, "truncated": False}
    columns = [str(c) for c in df.columns]
    row_count = len(df)
    truncated = row_count > max_rows
    sliced = df
    if truncated:
        date_col = _find_date_column(df)
        if date_col is not None:
            dated = df.copy()
            dated["__payload_date__"] = pd.to_datetime(dated[date_col], errors="coerce")
            dated = dated.sort_values("__payload_date__", kind="stable")
            sliced = dated.tail(max_rows).drop(columns="__payload_date__")
        else:
            sliced = df.head(max_rows)
    rows = []
    for row in sliced.itertuples(index=False, name=None):
        rows.append([_normalize_cell_value(v) for v in row])
    return {
        "columns": columns,
        "rows": rows,
        "row_count": row_count,
        "truncated": truncated
    }

def _build_expense_trend_points(sheets):
    sheet_name, df = _find_expense_sheet(sheets)
    if df is None or df.empty:
        return []

    date_col = _find_date_column(df)
    if date_col is None:
        return []

    balance_col = _find_first_column(df, ["现金及现金等价物+股票", "现金及现金等价物", "现金", "股票"])
    daily_average_col = _find_first_column(df, ["日均支出", "日均开销", "日均成本"])
    period_spend_col = _find_first_column(df, ["期间支出", "支出"])

    if balance_col is None and daily_average_col is None and period_spend_col is None:
        return []

    trend_points = []
    for _, row in df.iterrows():
        raw_date = _normalize_cell_value(row.get(date_col))
        if raw_date is None:
            continue

        parsed_date = pd.to_datetime(raw_date, errors="coerce")
        if pd.isna(parsed_date):
            continue

        balance = _coerce_number(row.get(balance_col)) if balance_col is not None else None
        daily_average = _coerce_number(row.get(daily_average_col)) if daily_average_col is not None else None
        period_spend = _coerce_number(row.get(period_spend_col)) if period_spend_col is not None else None

        if balance is None and daily_average is None and period_spend is None:
            continue

        trend_points.append(
            {
                "date": parsed_date.strftime("%Y-%m-%d"),
                "balance": balance,
                "daily_average": daily_average,
                "period_spend": period_spend,
                "sheet": sheet_name,
            }
        )

    trend_points.sort(key=lambda item: item["date"])
    return trend_points

def _build_balance_summary(sheets):
    daily_avg = _find_metric(sheets, ["日均支出", "日均开销", "日均成本"])
    monthly_total = _find_metric(sheets, ["月支出", "月度支出", "当月支出", "月总支出"])
    monthly_avg = _find_metric(sheets, ["月均支出", "月均开销", "月均成本"])

    latest_date = None
    if daily_avg and "sheet" in daily_avg:
        latest_date = _find_latest_date_in_df(sheets.get(daily_avg["sheet"]))
    if latest_date is None and monthly_total and "sheet" in monthly_total:
        latest_date = _find_latest_date_in_df(sheets.get(monthly_total["sheet"]))
    if latest_date is None and monthly_avg and "sheet" in monthly_avg:
        latest_date = _find_latest_date_in_df(sheets.get(monthly_avg["sheet"]))
    if latest_date is None:
        for df in sheets.values():
            latest_date = _find_latest_date_in_df(df)
            if latest_date:
                break

    days_in_month = 30
    if latest_date:
        days_in_month = calendar.monthrange(latest_date.year, latest_date.month)[1]

    daily_avg_value = daily_avg["value"] if daily_avg else None
    monthly_total_value = None
    if monthly_total:
        monthly_total_value = monthly_total["value"]
    elif monthly_avg:
        monthly_total_value = monthly_avg["value"]

    if daily_avg_value is None and monthly_total_value is not None:
        daily_avg_value = monthly_total_value / days_in_month if days_in_month else None

    per_minute = None
    if daily_avg_value is not None:
        per_minute = daily_avg_value / (24 * 60)
    elif monthly_total_value is not None:
        per_minute = (monthly_total_value / days_in_month) / (24 * 60) if days_in_month else None

    per_day_month = None
    if monthly_total_value is not None and days_in_month:
        per_day_month = monthly_total_value / days_in_month
    elif daily_avg_value is not None:
        per_day_month = daily_avg_value

    assets = {
        "fixed_assets": _find_metric(sheets, ["固定资产"]),
        "current_assets": _find_metric(sheets, ["流动资产"]),
        "total_assets": _find_metric(sheets, ["总资产", "资产合计"]),
        "liabilities": _find_metric(sheets, ["负债合计", "负债"]),
        "equity": _find_metric(sheets, ["净资产", "所有者权益", "股东权益"]),
        "cash_and_stock": _find_metric(sheets, ["现金及现金等价物+股票", "现金及现金等价物", "现金", "股票"])
    }

    budget = _build_budget_summary(sheets)

    return {
        "time_cost": {
            "daily_average": daily_avg_value,
            "monthly_total": monthly_total_value,
            "per_minute": per_minute,
            "per_day_month": per_day_month,
            "latest_date": latest_date.strftime("%Y-%m-%d") if latest_date else None,
            "source": {
                "daily_average": daily_avg,
                "monthly_total": monthly_total,
                "monthly_average": monthly_avg
            }
        },
        "assets": assets,
        "budget": budget
    }

def _build_balance_suggestions(summary):
    suggestions = []
    time_cost = summary.get("time_cost", {})
    assets = summary.get("assets", {})
    budget = summary.get("budget") or {}

    per_minute = time_cost.get("per_minute")
    per_day_month = time_cost.get("per_day_month")
    daily_average = time_cost.get("daily_average")

    if per_minute is not None:
        suggestions.append(f"时间成本：全天均摊每分钟约 {per_minute:.2f}，建议把高价值任务放在高专注时段，降低低价值碎片时间。")
    if per_day_month is not None:
        suggestions.append(f"月度均摊每日约 {per_day_month:.2f}，可结合预算上限设定每日支出阈值。")

    def extract_value(item):
        if not item:
            return None
        return item.get("value")

    total_assets = extract_value(assets.get("total_assets"))
    fixed_assets = extract_value(assets.get("fixed_assets"))
    current_assets = extract_value(assets.get("current_assets"))
    liabilities = extract_value(assets.get("liabilities"))
    cash_and_stock = extract_value(assets.get("cash_and_stock"))

    if total_assets and fixed_assets:
        fixed_ratio = fixed_assets / total_assets if total_assets else None
        if fixed_ratio is not None:
            if fixed_ratio > 0.6:
                suggestions.append("固定资产占比偏高，建议评估折旧压力和流动性风险，适度提升现金/可变资产比例。")
            elif fixed_ratio < 0.2:
                suggestions.append("固定资产占比较低，可结合长期规划评估必要的设备/能力投资。")

    if total_assets and current_assets:
        current_ratio = current_assets / total_assets if total_assets else None
        if current_ratio is not None and current_ratio < 0.25:
            suggestions.append("流动资产占比偏低，建议提高现金或短期可变资产以增强抗风险能力。")

    if total_assets and liabilities:
        debt_ratio = liabilities / total_assets if total_assets else None
        if debt_ratio is not None and debt_ratio > 0.6:
            suggestions.append("负债率偏高，建议优先偿还高利率负债，降低资金压力。")

    if cash_and_stock is not None and daily_average:
        cash_days = cash_and_stock / daily_average if daily_average else None
        if cash_days is not None:
            suggestions.append(f"现金+股票可覆盖约 {cash_days:.1f} 天日常开销，可据此设定安全垫目标。")

    monthly_required = budget.get("monthly_required")
    monthly_optional = budget.get("monthly_optional")
    if monthly_required is not None:
        suggestions.append(f"每月必须开支约 {monthly_required:.2f}，建议优先保障基础支出并定期复盘。")
    if monthly_optional is not None:
        suggestions.append(f"每月非必须开支约 {monthly_optional:.2f}，可设置弹性上限以控制超支。")

    if not suggestions:
        suggestions.append("当前可用指标较少，建议补充‘日均支出/资产/负债’等字段以获得更精确的优化建议。")

    return suggestions
# ... (existing imports/functions) ...

def get_camera_index():
    camera_index = 0
    # Simple logic to find USB camera, similar to main_window.py
    for camera_info in enumerate_cameras(cv2.CAP_MSMF):
        if "USB Camera" in camera_info.name:
            camera_index = camera_info.index
            break
    return camera_index

def identify_logs_folder(
    *,
    config_dir: str | Path | None = None,
    user_home: str | None = None,
    onedrive_env: str | None = None,
    onedrive_consumer_env: str | None = None,
    d_drive_root: str = r"D:\WANGBIAO",
):
    settings_file = get_media_paths_settings_file(config_dir=config_dir)
    return resolve_media_storage_paths(
        settings_file=settings_file,
        d_drive_root=d_drive_root,
        user_home=user_home,
        onedrive_env=onedrive_env,
        onedrive_consumer_env=onedrive_consumer_env,
    )

def find_latest_file_recursive(directory, extensions={'.jpg', '.png'}):
    latest_file = None
    latest_time = 0
    for root, dirs, files in os.walk(directory):
        for f in files:
            if os.path.splitext(f)[1].lower() in extensions:
                full_path = os.path.join(root, f)
                try:
                    mtime = os.path.getmtime(full_path)
                    if mtime > latest_time:
                        latest_time = mtime
                        latest_file = full_path
                except:
                    pass
    return latest_file


def initialize_latest_media_state():
    try:
        print("Scanning for latest existing images...")
        if not state.paths.get('photo') and state.photos_path:
            latest_photo = find_latest_file_recursive(state.photos_path)
            if latest_photo:
                state.paths['photo'] = latest_photo
                print(f"Found latest photo: {latest_photo}")

        if not state.paths.get('screenshot') and state.screenshots_path:
            latest_screen = find_latest_file_recursive(state.screenshots_path)
            if latest_screen:
                state.paths['screenshot'] = latest_screen
                print(f"Found latest screenshot: {latest_screen}")
    except Exception as e:
        print(f"Error finding latest files: {e}")

async def startup_event():
    print("Starting up server...")
    state.is_running = True
    try:
        # DEPRECATED IN FAVOR OF camera_loop: 
        # idx = get_camera_index()
        # state.camera = cv2.VideoCapture(idx)
        # if not state.camera.isOpened():
        #      print("Warning: Camera not opened")
        pass # Camera init moved to camera_loop to centralize resolution settings
    except Exception as e:
        print(f"Startup camera init error: {e}")
        
    # RESUME initialization (Unindented to run regardless of camera init success/failure)
    try:
        state.photos_path, state.screenshots_path = identify_logs_folder()
        print(f"----------------------------------------------------------------")
        print(f"[Storage] Photos Path: {state.photos_path}")
        print(f"[Storage] Screenshots Path: {state.screenshots_path}")
        print(f"----------------------------------------------------------------")
        
        state.monitor = Monitor(state.camera, state.paths, state.photos_path, state.screenshots_path)
        prewarm_runtime_models()

        thread_specs = (
            ("camera_loop", camera_loop),
            ("face_live_loop", face_live_loop),
            ("monitor_loop", monitor_loop),
            ("update_legacy_storage_stats", update_legacy_storage_stats),
            ("update_storage_stats", update_storage_stats),
            ("yolo_loop", yolo_loop),
        )
        for thread_name, thread_target in thread_specs:
            _start_background_thread_once(thread_name, thread_target)

        # Mount static directories for photos and plots
        _mount_static_once("/static/photos", state.photos_path, "photos")
        
        plot_dir = _get_plot_dir()
        plot_dir.mkdir(parents=True, exist_ok=True)
        _mount_static_once("/static/plots", plot_dir, "plots")
        
        _mount_static_once("/static/screenshots", state.screenshots_path, "screenshots")
        _start_background_thread_once("initialize_latest_media_state", initialize_latest_media_state)

    except Exception as e:
        print(f"Startup logic error: {e}")


async def shutdown_event():
    state.is_running = False
    for thread_name in state.background_thread_status:
        state.background_thread_status[thread_name] = False

    camera = state.camera
    state.camera = None
    if camera is not None:
        try:
            camera.release()
        except Exception as e:
            print(f"Shutdown camera release error: {e}")


@asynccontextmanager
async def lifespan(_app):
    await startup_event()
    try:
        yield
    finally:
        await shutdown_event()


app.router.lifespan_context = lifespan

def monitor_loop():
    print("Starting monitor loop (10s interval)...")
    while state.is_running:
        try:
            if state.monitor:
                # CRITICAL: Ensure Monitor uses the current active camera instance (initialized in camera_loop)
                # If camera is not ready yet, skip this cycle to avoid errors or default-init
                if state.camera is None or not state.camera.isOpened():
                    # print("Monitor skipping: Camera not ready")
                    time.sleep(2)
                    continue
                
                # Update the camera reference in monitor to match the global state (which is 4K)
                state.monitor.camera = state.camera
                
                # Run the periodic task (take photo, screenshot, etc.)
                state.monitor.run_task()

                photo_path = state.paths.get("photo")
                if photo_path and photo_path != state.last_processed_face_photo_path:
                    if process_captured_face_photo(photo_path):
                        state.last_processed_face_photo_path = photo_path
        except Exception as e:
            print(f"Monitor loop error: {e}")
        time.sleep(10)

def camera_loop():
    print(f"Starting camera loop... Camera Index: {get_camera_index()}")
    while state.is_running:
        if state.camera is None:
             idx = get_camera_index()
             try:
                 # Use DirectShow (CAP_DSHOW) on Windows for better resolution control
                 state.camera = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                 
                 # Request 4K resolution (16:9)
                 target_w, target_h = 3840, 2160
                 state.camera.set(cv2.CAP_PROP_FRAME_WIDTH, target_w)
                 state.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, target_h)
                 
                 # Verify actual resolution
                 actual_w = state.camera.get(cv2.CAP_PROP_FRAME_WIDTH)
                 actual_h = state.camera.get(cv2.CAP_PROP_FRAME_HEIGHT)
                 print(f"Camera Initialized: Requested {target_w}x{target_h}, Got {int(actual_w)}x{int(actual_h)}")
                 
                 # If 4K failed (e.g. got low res), try strict 1080p fallback
                 if actual_w < 1280: 
                     print("4K failed or ignored, trying strict 1080p force...")
                     state.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                     state.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                     print(f"Fallback resolution: {int(state.camera.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(state.camera.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
                     
             except Exception as e:
                 print(f"Camera init failed: {e}")
                 time.sleep(2)
                 continue

        if state.camera and state.camera.isOpened():
            try:
                ret, frame = state.camera.read()
                if ret:
                    with state.lock:
                        state.latest_frame = frame
                else:
                    print("Warning: Can't receive frame (stream end?). Exiting ...")
                    state.camera.release()
                    state.camera = None
                    time.sleep(2)
            except Exception as e:
                print(f"Camera read error: {e}")
                time.sleep(1)
        else:
             print("Camera not opened, retrying...")
             state.camera = None
             time.sleep(2)
        time.sleep(0.03)


def face_live_loop():
    print("Starting live face analysis loop...")
    while state.is_running:
        if not has_active_face_live_viewer():
            time.sleep(FACE_LIVE_IDLE_INTERVAL_SECONDS)
            continue

        frame_copy = None
        with state.lock:
            if state.latest_frame is not None:
                frame_copy = state.latest_frame.copy()

        if frame_copy is not None:
            try:
                detector, parser, config = get_face_analysis_runtime()
                result = analyze_image_data(frame_copy, detector=detector, parser=parser, config=config)
                update_live_face_overlay_state(result)
                store_live_face_result(result)
            except Exception as exc:
                print(f"Live face analysis error: {exc}")

        time.sleep(FACE_LIVE_SAMPLE_INTERVAL_SECONDS)

def yolo_loop():
    print("Starting YOLO detection background thread...")
    try:
        model = get_yolo_model()
        # Initialize an empty run to warm up the model
        import numpy as np
        dummy_img = np.zeros((640, 640, 3), dtype=np.uint8)
        model.predict(source=dummy_img, verbose=False, imgsz=640)
        print("YOLO model warmed up successfully.")
    except Exception as e:
        print(f"Failed to load YOLO model in thread: {e}")
        return

    while state.is_running:
        if not should_run_yolo_detection():
            with state.lock:
                state.person_boxes = []
            time.sleep(1)
            continue
            
        frame_copy = None
        with state.lock:
            if state.latest_frame is not None:
                frame_copy = state.latest_frame.copy()

        if frame_copy is not None:
            try:
                # Run detection on a resized frame to save CPU/GPU if needed, 
                # but ultralytics handles padding/resizing automatically based on imgsz.
                # using a standard surveillance confidence threshold to reduce false positives
                results = model.predict(
                    source=frame_copy,
                    verbose=False,
                    conf=PERSON_DETECTION_CONFIDENCE,
                    imgsz=640,
                )
                
                boxes = []
                if results and len(results) > 0:
                    for box in results[0].boxes:
                        if int(box.cls[0]) == 0:  # 0 is 'person' class in COCO
                            x1, y1, x2, y2 = box.xyxy[0].tolist()
                            boxes.append((int(x1), int(y1), int(x2), int(y2)))
                
                with state.lock:
                    state.person_boxes = boxes
                    
            except Exception as e:
                print(f"YOLO detection error: {e}")
        
        # Don't hit 100% CPU on this thread, YOLO inference takes time anyway, 
        # but yield a bit to prevent lock starvation
        time.sleep(0.1)

def generate_frames():
    register_video_stream_client()
    try:
        while True:
            frame = None
            overlay_score = None
            with state.lock:
                if state.latest_frame is not None:
                    frame = state.latest_frame.copy()
                else:
                    # Create a black placeholder image (16:9 aspect ratio)
                    import numpy as np
                    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                    cv2.putText(frame, "Camera Offline", (400, 360), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 2)
                overlay_score = state.latest_live_face_score

                # Draw YOLO bounding boxes if enabled
                if state.show_person_box and frame is not None:
                    for (x1, y1, x2, y2) in state.person_boxes:
                        # Neon Green box
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 3)
                        # Keep the person label above the box even when using a large font.
                        person_font = cv2.FONT_HERSHEY_SIMPLEX
                        person_label = "Person"
                        (_, person_text_height), person_baseline = cv2.getTextSize(
                            person_label,
                            person_font,
                            FACE_OVERLAY_PERSON_FONT_SCALE,
                            FACE_OVERLAY_PERSON_THICKNESS,
                        )
                        person_y = max(person_text_height + person_baseline + 8, y1 - 16)
                        cv2.putText(
                            frame,
                            person_label,
                            (x1, person_y),
                            person_font,
                            FACE_OVERLAY_PERSON_FONT_SCALE,
                            (0, 255, 0),
                            FACE_OVERLAY_PERSON_THICKNESS,
                        )
                        score_label = format_live_face_score_label(overlay_score)
                        font = cv2.FONT_HERSHEY_SIMPLEX
                        font_scale = FACE_OVERLAY_SCORE_FONT_SCALE
                        thickness = FACE_OVERLAY_SCORE_THICKNESS
                        padding = FACE_OVERLAY_SCORE_PADDING
                        (text_width, text_height), baseline = cv2.getTextSize(score_label, font, font_scale, thickness)
                        text_x = max(6, x2 - text_width)
                        text_y = max(text_height + baseline + padding, y1 - 12)
                        background_tl = (
                            max(0, text_x - padding),
                            max(0, text_y - text_height - baseline - padding),
                        )
                        background_br = (
                            min(frame.shape[1] - 1, text_x + text_width + padding),
                            min(frame.shape[0] - 1, text_y + padding),
                        )
                        cv2.rectangle(frame, background_tl, background_br, (0, 255, 0), -1)
                        cv2.putText(frame, score_label, (text_x, text_y), font, font_scale, (0, 0, 0), thickness)

            ret, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(0.04)
    finally:
        unregister_video_stream_client()

@app.get("/api/stream")
async def video_feed():
    return StreamingResponse(generate_frames(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/api/status")
async def get_status():
    return {
        "camera_online": state.camera.isOpened() if state.camera else False,
        "show_person_box": state.show_person_box,
        "paths": state.paths,
        "photos_path": state.photos_path,
        "screenshots_path": state.screenshots_path,
        "cwd": os.getcwd()
    }

@app.post("/api/toggle_detection")
async def toggle_detection():
    with state.lock:
        state.show_person_box = not state.show_person_box
        if not state.show_person_box:
            state.person_boxes = []  # Clear boxes immediately when turned off
    return {"status": "success", "show_person_box": state.show_person_box}

@app.get("/api/sys_stats")
async def get_sys_stats():
    try:
        cpu_usage = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        
        # Use cached sizes from background thread (avoid blocking event loop)
        photos_size = state.photos_size
        screenshots_size = state.screenshots_size
        legacy_size = state.legacy_size
        
        total, used, free = shutil.disk_usage(state.photos_path or ".")
        
        return {
            "cpu_usage": cpu_usage,
            "memory_used_gb": round(memory.used / (1024**3), 2),
            "memory_total_gb": round(memory.total / (1024**3), 2),
            "memory_percent": memory.percent,
            "disk_free_gb": round(free / (1024**3), 2),
            "storage_used_mb": round((photos_size + screenshots_size + legacy_size) / (1024**2), 2)
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/open_folder")
async def open_folder(request: Request):
    data = await request.json()
    folder_type = data.get("type")
    
    base_path = None
    if folder_type == "photo":
        base_path = state.photos_path
    elif folder_type == "screenshot":
        base_path = state.screenshots_path
        
    print(f"[OpenFolder] Request for type: {folder_type}, Base Path: {base_path}")

    if base_path and os.path.exists(base_path):
        try:
            # Construct hourly path: base / YYYY / MM / DD / HH
            now = datetime.now()
            year = now.strftime('%Y')
            month = now.strftime('%m')
            day = now.strftime('%d')
            hour = now.strftime('%H')
            
            # Try most specific path first, then fallback
            candidates = [
                os.path.join(base_path, year, month, day, hour),
                os.path.join(base_path, year, month, day),
                os.path.join(base_path, year, month),
                os.path.join(base_path, year),
                base_path
            ]
            
            target_path = base_path
            for path in candidates:
                if os.path.exists(path):
                    target_path = path
                    break
            
            print(f"[OpenFolder] Opening target path: {target_path}")
            
            # Use os.startfile for native Windows behavior
            os.startfile(target_path)
            return {"status": "success", "opened": target_path}
        except Exception as e:
            print(f"[OpenFolder] Error: {e}")
            return JSONResponse(status_code=500, content={"error": str(e)})
    
    print(f"[OpenFolder] Base path not found or invalid.")
    return JSONResponse(status_code=404, content={"error": "Folder path not found or not set"})

@app.get("/api/aqi")
async def get_aqi_stats(lat: Optional[float] = None, lon: Optional[float] = None):
    """Fetch current AQI (US) based on Location (Default: SJTU Minhang)"""
    def build_unavailable_payload(error_message: str | None = None):
        payload = {
            "aqi": None,
            "city": city,
            "level": "Unavailable",
            "color": "#b2bec3",
            "status": "unavailable",
            "lat": target_lat,
            "lon": target_lon,
        }
        if error_message:
            payload["error"] = error_message
        return payload

    try:
        # Default to Shanghai Jiao Tong University Minhang Campus
        # Lat: 31.025, Lon: 121.433
        target_lat = 31.025
        target_lon = 121.433
        city = "SJTU Minhang"
        
        # Only use provided coordinates if they seem valid and distinct from a generic VPN exit?
        # User requested "Directly display...", so let's prefer the hardcoded value 
        # unless we are very sure about the frontend provided ones.
        # But for now, to satisfy "Then just display...", I will default to these 
        # and only override if the frontend EXPLICITLY sends something different 
        # AND we trust it. 
        # Actually, let's just make it the default fallback instead of IP.
        # If frontend sends coordinates (permission granted), it might be accurate.
        # If permission denied, frontend sends null, we use SJTU.
        
        if lat is not None and lon is not None:
             target_lat = lat
             target_lon = lon
             city = "Current Location" 
        
        print(f"[AQI] Fetching for Lat: {target_lat}, Lon: {target_lon}, City: {city}")

        # 2. Get API (US Standard) from Open-Meteo
        aqi_url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={target_lat}&longitude={target_lon}&current=us_aqi"
        
        aqi_res = await asyncio.to_thread(requests.get, aqi_url, timeout=5)
        if not aqi_res.ok:
            return build_unavailable_payload(f"AQI API failed with status {aqi_res.status_code}")
            
        aqi_data = aqi_res.json()
        current = aqi_data.get("current", {})
        us_aqi = current.get("us_aqi")
        
        if us_aqi is None:
             return build_unavailable_payload("No AQI data")
              
        # Determine Level
        level = "Good"
        color = "#00e400" # Green
        if us_aqi > 50:
            level = "Moderate"
            color = "#ffff00" # Yellow
        if us_aqi > 100:
            level = "Unhealthy for Sensitive Groups"
            color = "#ff7e00" # Orange
        if us_aqi > 150:
            level = "Unhealthy"
            color = "#ff0000" # Red
        if us_aqi > 200:
            level = "Very Unhealthy"
            color = "#8f3f97" # Purple
        if us_aqi > 300:
            level = "Hazardous"
            color = "#7e0023" # Maroon
            
        return {
            "aqi": us_aqi,
            "city": city,
            "level": level,
            "color": color,
            "status": "ok",
            "lat": target_lat,
            "lon": target_lon
        }
        
    except Exception as e:
        print(f"AQI Error: {e}")
        return build_unavailable_payload(str(e))

@app.get("/api/latest_images")
def get_latest_images():
    try:
        photo_path = state.paths.get('photo')
        screenshot_path = state.paths.get('screenshot')
        
        photo_url = None
        if photo_path and state.photos_path:
            try:
                rel_path = os.path.relpath(photo_path, state.photos_path)
                rel_path = rel_path.replace("\\", "/") # Ensure web-friendly slashes
                photo_url = f"/static/photos/{rel_path}"
            except ValueError:
                photo_url = f"/static/photos/{os.path.basename(photo_path)}"
            
        screenshot_url = None
        if screenshot_path and state.screenshots_path:
            try:
                # Always relative to screenshots_path mount
                rel_path = os.path.relpath(screenshot_path, state.screenshots_path)
                rel_path = rel_path.replace("\\", "/")
                screenshot_url = f"/static/screenshots/{rel_path}"
            except ValueError:
                screenshot_url = f"/static/screenshots/{os.path.basename(screenshot_path)}"

        return {
            "photo": photo_url,
            "screenshot": screenshot_url,
            "photo_name": os.path.basename(photo_path) if photo_path else "",
            "screenshot_name": os.path.basename(screenshot_path) if screenshot_path else ""
        }
    except Exception as e:
        print(f"ERROR in get_latest_images: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/image_proxy")
async def image_proxy(path: str):
    """Proxy endpoint to serve local images not in static directories"""
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "File not found"})
    
    # Security: only allow images with valid extensions
    valid_exts = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'}
    if os.path.splitext(path)[1].lower() not in valid_exts:
         return JSONResponse(status_code=400, content={"error": "Invalid file type"})
    
    # Security: restrict to allowed directories only
    abs_path = os.path.abspath(path)
    allowed_dirs = [
        state.photos_path,
        state.screenshots_path,
        str(_get_plot_dir()),
        _get_history_dir(),
    ]
    def _is_within_allowed_dir(candidate_path, allowed_dir):
        if not allowed_dir:
            return False
        try:
            return os.path.commonpath([candidate_path, os.path.abspath(allowed_dir)]) == os.path.abspath(allowed_dir)
        except ValueError:
            return False

    if not any(_is_within_allowed_dir(abs_path, d) for d in allowed_dirs if d):
        return JSONResponse(status_code=403, content={"error": "Access denied: path not in allowed directories"})
         
    return FileResponse(abs_path)

@app.post("/api/plots/refresh")
async def refresh_plots():
    # Locate plot.py in src/scripts
    current_dir = os.path.dirname(os.path.abspath(__file__)) # src/server.py -> src
    script_path = os.path.join(current_dir, "scripts", "plot.py")
    
    if not os.path.exists(script_path):
        # Fallback to absolute path check
        script_path = os.path.abspath("src/scripts/plot.py")

    if not os.path.exists(script_path):
        return JSONResponse(status_code=404, content={"error": "plot.py not found"})

    def run_plot_script():
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        subprocess.run(
            [sys.executable, script_path, "--dark"],
            check=True,
            env=env,
            cwd=str(_get_runtime_workdir()),
        )

    try:
        await asyncio.to_thread(run_plot_script)
    except Exception as e:
        print(f"Error refreshing plots: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

    print("Plots refreshed successfully")
    return {"message": "Plots refreshed successfully"}

def ensure_thumbnail(file_path, thumb_path):
    if not os.path.exists(thumb_path):
        try:
            img = cv2.imread(file_path)
            if img is not None:
                h, w = img.shape[:2]
                scale = 60.0 / float(h)
                new_w = int(w * scale)
                dim = (new_w, 60)
                resized = cv2.resize(img, dim, interpolation=cv2.INTER_AREA)
                cv2.imwrite(thumb_path, resized)
        except Exception as e:
            print(f"Error creating thumbnail for {file_path}: {e}")

@app.get("/api/plots/list")
async def list_plots():
    """Return list of all plot images for carousel display"""
    plot_dir = str(_get_plot_dir())
    if not os.path.exists(plot_dir):
        return {"plots": [], "error": "plot_outputs directory not found"}
    
    thumb_dir = os.path.join(plot_dir, "thumbnails")
    if not os.path.exists(thumb_dir):
        os.makedirs(thumb_dir, exist_ok=True)
    
    try:
        files = [
            f for f in os.listdir(plot_dir)
            if f.endswith(".png")
            and not f.startswith("plot_collage")
            and not f.endswith("_screen.png")
        ]
        
        order = [
            "weight_bodyfat", "time_allocation_bar", "time_trend_screen_remaining",
            "time_trend_averages", "time_trend_delta", "running_pace",
            "radar_goal", "hhh_frequency", "hhh_interval_trend", "balance_sheet"
        ]
        
        def sort_key(name):
            for index, prefix in enumerate(order):
                if name.startswith(prefix):
                    return (index, name)
            return (len(order), name)
        
        sorted_files = sorted(files, key=sort_key)
        
        plot_list = []
        for f in sorted_files:
            file_path = os.path.join(plot_dir, f)
            thumb_path = os.path.join(thumb_dir, f)
            await asyncio.to_thread(ensure_thumbnail, file_path, thumb_path)
            plot_list.append({
                "name": f,
                "url": f"/static/plots/{f}",
                "thumbnail_url": f"/static/plots/thumbnails/{f}"
            })
        
        return {
            "plots": plot_list,
            "count": len(plot_list)
        }
    except Exception as e:
        print(f"Error listing plots: {e}")
        return {"plots": [], "error": str(e)}


@app.get("/api/plots/data")
async def get_plot_dashboard_data():
    try:
        from src.services.plot_dashboard import build_plot_dashboard_data

        payload = await asyncio.to_thread(build_plot_dashboard_data)
        return payload
    except Exception as e:
        print(f"Error building plot dashboard data: {e}")
        return JSONResponse(status_code=500, content={"error": str(e), "charts": [], "count": 0})

@app.get("/api/action_plan/today")
async def get_today_action_plan():
    """Return today's latest action plan if it exists"""
    today = datetime.now().strftime("%Y%m%d")

    try:
        latest_file = _get_latest_action_plan_file(today)
        if latest_file is None:
            return {
                "exists": False,
                "analysis": None,
                "plan": None,
                "meta": None,
                "date": today,
            }

        payload = _load_action_plan_payload(latest_file)
        if not payload:
            return {
                "exists": False,
                "analysis": None,
                "plan": None,
                "meta": None,
                "date": today,
                "error": f"Invalid action plan payload: {os.path.basename(latest_file)}",
            }

        return {
            "exists": True,
            "analysis": payload.get("analysis"),
            "plan": payload.get("plan"),
            "meta": payload.get("meta"),
            "date": payload.get("date") or today,
            "filename": os.path.basename(latest_file),
            "id": payload.get("id"),
        }
    except Exception as e:
        return {
            "exists": False,
            "analysis": None,
            "plan": None,
            "meta": None,
            "error": str(e),
            "date": today,
        }

class ChatRequest(BaseModel):
    message: str
    model: Optional[str] = None
    context_file: Optional[str] = None
    reasoning_effort: Optional[str] = None
    client_sent_at: Optional[str] = None


_VALID_REASONING_EFFORTS = {"low", "medium", "high", "xhigh"}


def _normalize_reasoning_effort(reasoning_effort: Optional[str]) -> str:
    if reasoning_effort in _VALID_REASONING_EFFORTS:
        return reasoning_effort
    return "medium"


def _get_history_dir() -> str:
    return str(Config.get_history_dir())


def _get_latest_context_file() -> str:
    return os.path.join(_get_history_dir(), "latest_context.json")


def _get_action_plan_context_file() -> str:
    return os.path.join(_get_history_dir(), "latest_action_plan_context.json")


def _get_context_session_file(path: str) -> Path:
    context_path = Path(path)
    return context_path.with_name(f"{context_path.stem}_session.json")


def _read_context_session_payload(path: str):
    session_path = _get_context_session_file(path)
    if not session_path.exists():
        return None

    try:
        with open(session_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError):
        return None

    return payload if isinstance(payload, dict) else None


def _read_context_session_id(path: str):
    payload = _read_context_session_payload(path)
    if not payload:
        return None

    session_id = payload.get("session_id")
    return str(session_id).strip() if session_id else None


def _write_context_session_payload(path: str, payload):
    session_path = _get_context_session_file(path)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    with open(session_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _remove_context_session_payload(path: str):
    session_path = _get_context_session_file(path)
    if session_path.exists():
        session_path.unlink(missing_ok=True)


def _load_context_session_stats(path: str):
    session_id = _read_context_session_id(path)
    if not session_id:
        return None

    try:
        return get_session_usage_summary(
            session_id,
            db_file=Path(_get_history_dir()) / "state.db",
        )
    except Exception as exc:
        logging.warning("Failed to load context session stats for %s: %s", path, exc)
        return None


def _load_context_messages(path: str):
    context_path = Path(path)
    if not context_path.exists():
        return []

    try:
        with open(context_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError):
        return []

    return payload if isinstance(payload, list) else []


def _write_context_messages(path: str, messages):
    context_path = Path(path)
    context_path.parent.mkdir(parents=True, exist_ok=True)
    with open(context_path, "w", encoding="utf-8") as handle:
        json.dump(messages, handle, ensure_ascii=False, indent=2)


def _build_chat_display_messages(messages):
    display_messages = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        display_messages.append({
            "role": "assistant",
            "content": content,
        })
    return display_messages


def _build_chat_context_payload():
    action_plan_context_path = Path(_get_action_plan_context_file())
    stats = _load_context_session_stats(_get_latest_context_file())
    if not action_plan_context_path.exists():
        return {
            "base_context_version": "empty",
            "has_action_plan_context": False,
            "display_messages": [],
            "stats": stats,
        }

    try:
        digest = hashlib.sha1(action_plan_context_path.read_bytes()).hexdigest()
    except OSError:
        digest = "empty"

    action_plan_messages = _load_context_messages(str(action_plan_context_path))
    return {
        "base_context_version": digest or "empty",
        "has_action_plan_context": True,
        "display_messages": _build_chat_display_messages(action_plan_messages),
        "stats": stats,
    }


def _load_action_plan_payload(path: str):
    action_plan_path = Path(path)
    if not action_plan_path.exists():
        return None

    try:
        with open(action_plan_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError):
        return None

    return payload if isinstance(payload, dict) else None


def _get_latest_action_plan_file(target_date: Optional[str] = None):
    files = _list_today_action_plan_files(target_date)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def _list_today_action_plan_files(target_date: Optional[str] = None):
    today = target_date or datetime.now().strftime("%Y%m%d")
    pattern = os.path.join(_get_history_dir(), f"action_plan_{today}_*.json")
    return glob.glob(pattern)


def _replace_today_action_plan_files(previous_files):
    current_files = _list_today_action_plan_files()
    if not current_files:
        return None

    keep_file = max(current_files, key=os.path.getmtime)
    previous_file_paths = {os.path.abspath(path) for path in previous_files}
    current_file_paths = {os.path.abspath(path) for path in current_files}
    created_files = current_file_paths - previous_file_paths

    if previous_file_paths and not created_files and os.path.abspath(keep_file) in previous_file_paths:
        return keep_file

    for path in current_files:
        if os.path.abspath(path) == os.path.abspath(keep_file):
            continue
        try:
            os.remove(path)
        except OSError as exc:
            print(f"Failed to remove replaced action plan file {path}: {exc}")

    return keep_file


class ActionPlanRequest(BaseModel):
    reasoning_effort: Optional[str] = None
    model: Optional[str] = None
    replace_today: bool = False


@app.get("/api/chat/context")
async def get_chat_context():
    return _build_chat_context_payload()


@app.delete("/api/chat/context")
async def reset_chat_context():
    action_plan_messages = _load_context_messages(_get_action_plan_context_file())
    _write_context_messages(_get_latest_context_file(), action_plan_messages)
    action_plan_session_payload = _read_context_session_payload(_get_action_plan_context_file())
    if action_plan_session_payload:
        _write_context_session_payload(_get_latest_context_file(), action_plan_session_payload)
    else:
        _remove_context_session_payload(_get_latest_context_file())
    return _build_chat_context_payload()


@app.get("/api/usage")
async def get_usage_dashboard():
    return get_usage_dashboard_snapshot(
        db_file=Path(Config.get_history_dir()) / "state.db",
    )


@app.get("/api/llm_models")
async def list_llm_models():
    try:
        client = LLMClient()
    except Exception as error:
        return {"models": [], "providers": [], "default_model": None, "error": str(error)}

    providers = client.get_model_catalog()
    seen = set()
    models = []
    for provider in providers:
        for model in provider.get("models", []):
            if model and model not in seen:
                seen.add(model)
                models.append(model)

    return {
        "models": models,
        "providers": providers,
        "default_model": providers[0]["model"] if providers else None,
    }

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    context_file = request.context_file
    if not context_file:
         context_file = _get_latest_context_file()

    run_prompt_args = [
        "--chat_message", request.message,
        "--context_file", context_file
    ]
    if request.model:
        run_prompt_args.extend(["--model", request.model])
    if request.client_sent_at:
        run_prompt_args.extend(["--client_sent_at", request.client_sent_at])
    cmd, run_prompt_cwd = _build_run_prompt_subprocess(run_prompt_args)
    
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["AI_REASONING_EFFORT"] = _normalize_reasoning_effort(request.reasoning_effort)

    async def process_chat_stream():
        proc = None
        stderr_task = None
        stderr_lines = []
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=run_prompt_cwd,
                env=env
            )
            stderr_task = asyncio.create_task(
                _drain_subprocess_stderr(proc.stderr, "chat", stderr_lines)
            )
            
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                decoded = _decode_subprocess_chunk(line)
            
                msg = decoded.strip()
                if msg:
                    yield json.dumps({"log": msg}) + "\n"
            
            await proc.wait()
            if stderr_task is not None:
                await stderr_task
            
            if proc.returncode != 0:
                err_msg = "\n".join(stderr_lines).strip() or f"run_prompt.py exited with code {proc.returncode}"
                logging.error("Chat subprocess failed: %s", err_msg)
                yield json.dumps({"error": err_msg}) + "\n"
        except asyncio.CancelledError:
            logging.warning("Chat stream cancelled by client")
            if proc is not None:
                proc.terminate()
            raise
        finally:
            if stderr_task is not None and not stderr_task.done():
                stderr_task.cancel()
                with suppress(asyncio.CancelledError):
                    await stderr_task
            if proc is not None and proc.returncode is None:
                logging.warning("Killing orphan chat subprocess")
                proc.kill()

    try:
        return StreamingResponse(process_chat_stream(), media_type="application/x-ndjson")
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/action_plan")
async def generate_action_plan(request: Optional[ActionPlanRequest] = None):
    run_prompt_args = []
    
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["AI_REASONING_EFFORT"] = _normalize_reasoning_effort(
        request.reasoning_effort if request else None,
    )
    selected_model = request.model if request else None
    if selected_model:
        run_prompt_args.append(f"--model={selected_model}")
    cmd, run_prompt_cwd = _build_run_prompt_subprocess(run_prompt_args)
    replace_today = request.replace_today if request else False
    previous_today_files = _list_today_action_plan_files() if replace_today else []
    
    async def process_stream():
        stderr_task = None
        stderr_lines = []
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=run_prompt_cwd,
            env=env
        )
        logging.info(
            "Action plan subprocess started: model=%s reasoning_effort=%s replace_today=%s",
            selected_model or "<auto>",
            env["AI_REASONING_EFFORT"],
            replace_today,
        )
        stderr_task = asyncio.create_task(
            _drain_subprocess_stderr(proc.stderr, "action_plan", stderr_lines)
        )
        
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                decoded = _decode_subprocess_chunk(line)
                yield json.dumps({"log": decoded}) + "\n"
                
            await proc.wait()
            if stderr_task is not None:
                await stderr_task

            if proc.returncode != 0:
                err_msg = "\n".join(stderr_lines).strip() or f"run_prompt.py exited with code {proc.returncode}"
                logging.error("Action plan subprocess failed: %s", err_msg)
                yield json.dumps({"error": err_msg}) + "\n"
            elif replace_today:
                logging.info("Action plan subprocess completed successfully; replacing today's saved files")
                _replace_today_action_plan_files(previous_today_files)
            else:
                logging.info("Action plan subprocess completed successfully")
            
        except asyncio.CancelledError:
            logging.warning("Action plan stream cancelled by client")
            proc.terminate()
            raise
        finally:
            if stderr_task is not None and not stderr_task.done():
                stderr_task.cancel()
                with suppress(asyncio.CancelledError):
                    await stderr_task
            if proc.returncode is None:
                logging.warning("Killing orphan action plan subprocess")
                proc.kill()
    
    return StreamingResponse(process_stream(), media_type="application/x-ndjson")

@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    original_filename = file.filename or "recording.webm"
    ext = os.path.splitext(original_filename)[1] or ".webm"
    
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    temp_fd, temp_filename = tempfile.mkstemp(prefix="temp_audio_", suffix=ext, dir=project_root)
    
    print(f"[Transcribe] Saving uploaded file to: {temp_filename}")
    
    with os.fdopen(temp_fd, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
        print(f"[Transcribe] File size: {len(content)} bytes")
        
    cmd, run_prompt_cwd = _build_run_prompt_subprocess(["--transcribe", temp_filename])
    print(f"[Transcribe] Running command: {' '.join(cmd)}")
    
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=run_prompt_cwd,
            env=env
        )
        
        stdout, stderr = await proc.communicate()
        
        output = ""
        try:
            output = stdout.decode('utf-8')
        except:
            output = stdout.decode('gbk', errors='replace')
        
        if stderr:
            try:
                stderr_text = stderr.decode('utf-8')
            except:
                stderr_text = stderr.decode('gbk', errors='replace')
            print(f"[Transcribe] Stderr: {stderr_text}")
        else:
            stderr_text = ""
        
        print(f"[Transcribe] Stdout: {output}")
            
        transcription = ""
        transcription_error = ""
        for line in output.splitlines():
            if line.startswith("TRANSCRIPTION_RESULT:"):
                transcription = line.replace("TRANSCRIPTION_RESULT:", "").strip()
                break
            if line.startswith("TRANSCRIPTION_ERROR:"):
                transcription_error = line.replace("TRANSCRIPTION_ERROR:", "").strip()
        
        if proc.returncode != 0:
            details = transcription_error or stderr_text or output.strip()
            return JSONResponse(
                status_code=500,
                content={"error": "Transcription failed", "details": details},
            )
        
        if not transcription:
            details = transcription_error or stderr_text or output.strip() or "No transcription result returned"
            return JSONResponse(
                status_code=500,
                content={"error": "Transcription failed", "details": details},
            )
        
        print(f"[Transcribe] Result: '{transcription}'")
                
        return {"transcription": transcription}
    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except Exception:
                pass
        if os.path.exists(temp_filename):
            try:
                os.remove(temp_filename)
            except OSError as exc:
                print(f"[Transcribe] Failed to remove temp file {temp_filename}: {exc}")

@app.get("/api/action_plan_content")
async def get_action_plan_content():
    try:
        latest_file = _get_latest_action_plan_file()
        if latest_file is None:
            return {"exists": False, "analysis": None, "plan": None, "meta": None}

        payload = _load_action_plan_payload(latest_file)
        if not payload:
            return {"exists": False, "analysis": None, "plan": None, "meta": None}

        return {
            "exists": True,
            "analysis": payload.get("analysis"),
            "plan": payload.get("plan"),
            "meta": payload.get("meta"),
            "timestamp": os.path.getctime(latest_file),
            "filename": os.path.basename(latest_file),
            "id": payload.get("id"),
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/system_logs")
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

@app.get("/api/balance_sheet")
async def get_balance_sheet():
    try:
        path = DataLoader.resolve_data_path("Balance Sheet.xlsx")
        sheets = DataLoader.load_excel_sheets(path)

        if not sheets:
            return JSONResponse(status_code=404, content={"error": "No sheets found in Balance Sheet.xlsx"})

        summary = _build_balance_summary(sheets)
        suggestions = _build_balance_suggestions(summary)
        trend_points = _build_expense_trend_points(sheets)

        sheet_payloads = []
        for sheet_name, df in sheets.items():
            payload = _sheet_to_payload(df, max_rows=200)
            payload["name"] = sheet_name
            sheet_payloads.append(payload)

        return {
            "source": {
                "path": str(path),
                "sheet_count": len(sheets),
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            "summary": summary,
            "suggestions": suggestions,
            "trend_points": trend_points,
            "sheets": sheet_payloads,
        }
    except FileNotFoundError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

@app.post("/api/face/analyze")
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

    current_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(current_dir, "scripts", "analyze_face.py")
    if not os.path.exists(script_path):
         script_path = os.path.abspath("src/scripts/analyze_face.py")
    
    def run_analysis():
        print("Starting face analysis...")
        try:
            log_path = _create_runtime_log_path("face-analysis", "face-analysis")
            with open(log_path, "a", encoding="utf-8", buffering=1) as log_file:
                log_file.write(f"\n=== Face analysis launch {datetime.now().isoformat()} ===\n")
                log_file.flush()
                subprocess.run(
                    [sys.executable, script_path],
                    check=True,
                    cwd=str(_get_runtime_workdir()),
                    stdout=log_file,
                    stderr=log_file,
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


@app.get("/api/face/live")
async def get_face_live(active: bool = False):
    if active:
        mark_face_live_viewer_active()

    camera_online = _camera_online()
    if not camera_online:
        return {
            "camera_online": False,
            "window_seconds": FACE_LIVE_WINDOW_SECONDS,
            "latest_score": None,
            "latest_datetime": "",
            "points": [],
        }

    points = snapshot_live_face_points()
    latest = points[-1] if points else None
    return {
        "camera_online": True,
        "window_seconds": FACE_LIVE_WINDOW_SECONDS,
        "latest_score": latest["score"] if latest else None,
        "latest_datetime": latest["datetime"] if latest else "",
        "points": points,
    }

@app.get("/api/face/report")
async def get_face_report():
    """Get the latest analysis report including extremes and plot URL"""
    try:
        db_file = _get_face_analysis_db_file()
        initialize_face_analysis_storage(db_file)
        report_json = load_face_report_cache(db_file)
        if not report_json:
            return {"error": "No report generated"}

        return build_face_report_response(report_json, state.photos_path)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/face/export_excel")
async def export_face_excel():
    """Export face analysis data to Excel"""
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(current_dir, "scripts", "analyze_face.py")
        if not os.path.exists(script_path):
             script_path = os.path.abspath("src/scripts/analyze_face.py")
             
        # Run script with --export flag
        proc = subprocess.run(
            [sys.executable, script_path, "--export"],
            capture_output=True,
            cwd=str(_get_runtime_workdir()),
        )

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

@app.get("/api/face/progress")
async def get_face_progress():
    """Get the current progress of face analysis"""
    try:
        db_file = _get_face_analysis_db_file()
        initialize_face_analysis_storage(db_file)
        data = load_face_progress_cache(db_file)

        if not data:
            return {"status": "idle", "percent": 0}

        # Check if stale (e.g. older than 1 minute)
        if time.time() - data.get("timestamp", 0) > 60:
             return {"status": "idle", "percent": 0}
             
        return data
    except Exception as e:
        return {"status": "error", "error": str(e)}

@app.get("/api/health/sedentary")
def get_sedentary_stats():
    """Returns the current continuous sitting duration from the monitor."""
    try:
        if not state.monitor:
             return {"status": "inactive"}

        now = time.time()
        heartbeat = getattr(state.monitor, "last_monitor_heartbeat", None)
        stale_timeout = getattr(
            state.monitor,
            "monitor_stale_timeout",
            getattr(state.monitor, "grace_period", None),
        )
        if heartbeat is not None and stale_timeout is not None and (now - heartbeat) >= stale_timeout:
             return {
                 "status": "active",
                 "is_sitting": False,
                 "duration_minutes": 0,
                 "threshold_minutes": state.monitor.sedentary_threshold // 60
             }

        start = state.monitor.continuous_sit_start
        if start is None:
             return {
                 "status": "active",
                 "is_sitting": False,
                 "duration_minutes": 0,
                 "threshold_minutes": state.monitor.sedentary_threshold // 60
             }

        duration_sec = now - start
        return {
             "status": "active",
             "is_sitting": True,
             "duration_minutes": int(duration_sec // 60),
             "duration_seconds": int(duration_sec),
             "threshold_minutes": state.monitor.sedentary_threshold // 60
        }
    except Exception as e:
         return {"status": "error", "error": str(e)}

@app.get("/api/project_progress")
async def get_project_progress():
    """Parse Prompt_Project_Management.md and git logs to return project momentum."""
    try:
        project_root = _get_project_progress_root()
        md_file = project_root / "Prompt_Project_Management.md"
        
        completed_tasks = []
        pending_tasks = []
        current_project = "General"
        
        if md_file.exists():
            with open(md_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines:
                    line = line.strip()
                    # Detect Headers as project groups
                    if line.startswith("## ") or line.startswith("### ") or line.startswith("#### "):
                        cleaned_header = re.sub(r'^#+\s*', '', line)
                        if cleaned_header and "任务" in cleaned_header or "项目" in cleaned_header:
                             current_project = cleaned_header
                             
                    # Detect completed tasks
                    elif line.startswith("- [X]") or line.startswith("- [x]"):
                        task_desc = line[5:].strip()
                        completed_tasks.append({"project": current_project, "task": task_desc, "status": "completed"})
                        
                    # Detect pending tasks
                    elif line.startswith("- [ ]"):
                         task_desc = line[5:].strip()
                         pending_tasks.append({"project": current_project, "task": task_desc, "status": "pending"})
        
        # Calculate stats
        total_tasks = len(completed_tasks) + len(pending_tasks)
        completion_rate = (len(completed_tasks) / total_tasks) if total_tasks > 0 else 0
        
        # Git commits (last 14 days). Packaged builds fall back to a bundled snapshot.
        recent_commits = _load_recent_git_commits(project_root)
        if not recent_commits:
            recent_commits = _load_project_activity_snapshot(project_root)
            
        return {
            "tasks": {
                "completed": completed_tasks,
                "pending": pending_tasks
            },
            "commits": recent_commits,
            "stats": {
                "total_tasks": total_tasks,
                "completed_tasks": len(completed_tasks),
                "completion_rate": completion_rate
            }
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()

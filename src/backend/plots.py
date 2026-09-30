"""Plot refresh and dashboard cache routes."""

import asyncio
import copy
import threading
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.core.config import Config
from src.utils.data_loader import DataLoader

router = APIRouter()

FACE_REPORT_PLOT_OUTPUT_DIR = None

_plot_refresh_lock = threading.Lock()

_plot_dashboard_cache_lock = threading.Lock()

_plot_dashboard_cache_key = None

_plot_dashboard_cache_payload = None

def _get_plot_dir():
    if FACE_REPORT_PLOT_OUTPUT_DIR:
        return Path(FACE_REPORT_PLOT_OUTPUT_DIR)
    return Path(Config.get_plot_dir())

def _file_signature(path):
    candidate = Path(path)
    try:
        stat = candidate.stat()
    except OSError:
        return (str(candidate), None, None)
    return (str(candidate), stat.st_mtime_ns, stat.st_size)

def _get_plot_dashboard_cache_key():
    mi_fitness_data_root = DataLoader.resolve_health_data_root("mi_fiteness_data")
    zepp_data_root = DataLoader.resolve_health_data_root("zepplift_data")
    source_paths = [
        DataLoader.resolve_data_path("Time.xlsx"),
        DataLoader.resolve_data_path("Balance Sheet.xlsx"),
        mi_fitness_data_root / "mi_fiteness_data" / "20260416_881116692_MiFitness_hlth_center_sport_record.csv",
        zepp_data_root / "zepplift_data" / "SPORT" / "SPORT_running_master.csv",
        zepp_data_root / "zepplift_data" / "SPORT" / "SPORT_1776331608562.csv",
    ]
    return tuple(_file_signature(path) for path in source_paths)

def _clear_plot_dashboard_cache():
    global _plot_dashboard_cache_key, _plot_dashboard_cache_payload
    with _plot_dashboard_cache_lock:
        _plot_dashboard_cache_key = None
        _plot_dashboard_cache_payload = None

@router.post("/api/v1/plots/refresh")
async def refresh_plots():
    if not _plot_refresh_lock.acquire(blocking=False):
        return JSONResponse(
            status_code=409,
            content={"error": "Plots refresh is already running", "status": "running"},
        )

    try:
        _clear_plot_dashboard_cache()
    except Exception as e:
        print(f"Error refreshing plots: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        _plot_refresh_lock.release()

    print("Plot dashboard data cache cleared")
    return {"message": "Plot dashboard data cache cleared", "status": "ready"}

@router.get("/api/v1/plots/data")
async def get_plot_dashboard_data():
    global _plot_dashboard_cache_key, _plot_dashboard_cache_payload
    try:
        from src.services.plot_dashboard import build_plot_dashboard_data

        cache_key = _get_plot_dashboard_cache_key()
        with _plot_dashboard_cache_lock:
            if _plot_dashboard_cache_key == cache_key and _plot_dashboard_cache_payload is not None:
                return copy.deepcopy(_plot_dashboard_cache_payload)

        payload = await asyncio.to_thread(build_plot_dashboard_data)
        with _plot_dashboard_cache_lock:
            _plot_dashboard_cache_key = cache_key
            _plot_dashboard_cache_payload = copy.deepcopy(payload)
        return payload
    except Exception as e:
        print(f"Error building plot dashboard data: {e}")
        return JSONResponse(status_code=500, content={"error": str(e), "charts": [], "count": 0})

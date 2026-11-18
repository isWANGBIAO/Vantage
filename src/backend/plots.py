"""Plot refresh and dashboard cache routes."""

import asyncio
import copy
import hashlib
import json
import os
import shutil
import tempfile
import threading
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from src.core.config import Config
from src.utils.data_loader import DataLoader

router = APIRouter()

FACE_REPORT_PLOT_OUTPUT_DIR = None

_plot_refresh_lock = threading.Lock()

_plot_dashboard_cache_lock = threading.Lock()

_plot_dashboard_cache_key = None

_plot_dashboard_cache_payload = None
_plot_dashboard_cache_generation = 0
_plot_dashboard_build_lock = threading.Lock()

def _get_plot_dir():
    if FACE_REPORT_PLOT_OUTPUT_DIR:
        return Path(FACE_REPORT_PLOT_OUTPUT_DIR)
    return Path(Config.get_plot_dir())

def _copy_plot_source_for_read(source, destination):
    """Windows copy access can succeed while Excel denies a direct read open."""
    if os.name != 'nt':
        shutil.copyfile(source, destination)
        return
    import ctypes

    copy_file = ctypes.WinDLL('kernel32', use_last_error=True).CopyFileW
    copy_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
    copy_file.restype = ctypes.c_int
    if not copy_file(str(source), str(destination), 1):
        raise ctypes.WinError(ctypes.get_last_error())


def _source_digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _file_signature(path):
    candidate = Path(path)
    try:
        before = candidate.stat()
    except FileNotFoundError:
        return (str(candidate), None, None)
    # A size/mtime-only key misses edits restored by sync tools or file copies.
    # Hash on the worker thread, then require the same physical file throughout.
    try:
        digest = _source_digest(candidate)
    except PermissionError:
        # Match the existing workbook loader's temporary-copy behavior without
        # shell commands, path interpolation, or modifying the original file.
        with tempfile.TemporaryDirectory(prefix='vantage-plot-fingerprint-') as directory:
            snapshot = Path(directory) / 'source.xlsx'
            _copy_plot_source_for_read(candidate, snapshot)
            digest = _source_digest(snapshot)
    after = candidate.stat()
    before_identity = (before.st_mtime_ns, before.st_ctime_ns, before.st_size, before.st_ino)
    after_identity = (after.st_mtime_ns, after.st_ctime_ns, after.st_size, after.st_ino)
    if before_identity != after_identity:
        raise _PlotSourceChanged('Plot source changed while fingerprinting')
    return (str(candidate), *after_identity, digest)

def _get_plot_dashboard_cache_key():
    source_paths = [
        DataLoader.resolve_data_path("Time.xlsx"),
        DataLoader.resolve_data_path("Balance Sheet.xlsx"),
    ]
    return tuple(_file_signature(path) for path in source_paths)

def _clear_plot_dashboard_cache():
    global _plot_dashboard_cache_key, _plot_dashboard_cache_payload, _plot_dashboard_cache_generation, _plot_dashboard_build_lock
    with _plot_dashboard_cache_lock:
        _plot_dashboard_cache_generation += 1
        _plot_dashboard_cache_key = None
        _plot_dashboard_cache_payload = None
        # Refresh starts a new generation rather than waiting on an obsolete
        # read. Its old writer must not publish or return stale chart data.
        _plot_dashboard_build_lock = threading.Lock()


class _PlotSourceChanged(RuntimeError):
    pass


def _plot_day():
    # Balance actual/forecast masks depend on today's date even without edits.
    return date.today().isoformat()


def _healthy_payload(payload):
    charts = payload.get('charts')
    return isinstance(charts, list) and not any(
        chart.get('retry_required', bool(chart.get('error'))) for chart in charts
    ) and not any(
        str(warning.get('id', '')).endswith('-unavailable') for warning in payload.get('warnings', [])
    )


def _read_plot_dashboard(known_revision):
    """Singleflight complete builds; changed/failed reads never become current."""
    global _plot_dashboard_cache_key, _plot_dashboard_cache_payload
    from src.services.plot_dashboard import build_plot_dashboard_data

    with _plot_dashboard_cache_lock:
        generation = _plot_dashboard_cache_generation
        build_lock = _plot_dashboard_build_lock

    with build_lock:
        for attempt in range(2):
            try:
                cache_key = (_get_plot_dashboard_cache_key(), _plot_day())
                with _plot_dashboard_cache_lock:
                    if generation != _plot_dashboard_cache_generation:
                        raise _PlotSourceChanged('Plot refresh superseded this read')
                    if _plot_dashboard_cache_key == cache_key and _plot_dashboard_cache_payload is not None:
                        revision = _plot_dashboard_cache_payload['source_revision']
                        if known_revision == revision:
                            return {'unchanged': True, 'source_revision': revision}
                        return copy.deepcopy(_plot_dashboard_cache_payload)

                payload = build_plot_dashboard_data()
                if cache_key != (_get_plot_dashboard_cache_key(), _plot_day()):
                    raise _PlotSourceChanged('Plot sources changed while building')
                with _plot_dashboard_cache_lock:
                    if generation != _plot_dashboard_cache_generation:
                        raise _PlotSourceChanged('Plot refresh superseded this read')
                    if not _healthy_payload(payload):
                        # Preserve useful initial diagnostics, but never tell a
                        # client this failed read is a reusable current version.
                        return {**payload, 'retry_required': True}
                    revision = hashlib.sha256(json.dumps((cache_key, generation), ensure_ascii=True).encode()).hexdigest()
                    result = {**payload, 'source_revision': revision}
                    _plot_dashboard_cache_key = cache_key
                    _plot_dashboard_cache_payload = copy.deepcopy(result)
                    return result
            except _PlotSourceChanged:
                with _plot_dashboard_cache_lock:
                    superseded = generation != _plot_dashboard_cache_generation
                if superseded or attempt:
                    raise
        raise _PlotSourceChanged('Plot sources are not stable')

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
async def get_plot_dashboard_data(known_revision: Annotated[str | None, Query(pattern=r'^[0-9a-f]{64}$')] = None):
    try:
        return await asyncio.to_thread(_read_plot_dashboard, known_revision)
    except (_PlotSourceChanged, OSError):
        return JSONResponse(status_code=503, content={
            'error': '图表数据暂时无法稳定读取，已保留原图，将自动重试。', 'retry_required': True,
        })
    except Exception as e:
        print(f"Error building plot dashboard data: {e}")
        return JSONResponse(status_code=500, content={"error": str(e), "charts": [], "count": 0})

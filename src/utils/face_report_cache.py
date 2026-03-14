import json
import os
import time
import urllib.parse
from pathlib import Path

from src.utils.face_analysis_db import (
    FACE_ANALYSIS_DB_FILE,
    load_face_report_cache as load_face_report_cache_from_db,
    save_face_report_cache as save_face_report_cache_to_db,
)
from src.services.face_analysis_pipeline import empty_trend_views

FACE_REPORT_CACHE_FILE = FACE_ANALYSIS_DB_FILE


def save_face_report_cache(report: dict, report_file: str | Path = FACE_REPORT_CACHE_FILE) -> Path:
    return save_face_report_cache_to_db(report, report_file)


def load_face_report_cache(report_file: str | Path = FACE_REPORT_CACHE_FILE) -> dict | None:
    return load_face_report_cache_from_db(report_file)


def build_face_report_response(report: dict, photos_path: str | None = None) -> dict:
    def path_to_url(path: str) -> str:
        if not path:
            return ""

        abs_path = os.path.abspath(path)
        if photos_path:
            abs_photos = os.path.abspath(photos_path)
            if abs_path.startswith(abs_photos):
                rel = os.path.relpath(abs_path, abs_photos).replace("\\", "/")
                return f"/static/photos/{rel}"

        encoded_path = urllib.parse.quote(abs_path)
        return f"/api/image_proxy?path={encoded_path}"

    trend_plot_path = report.get("trend_plot_path", "")
    trend_plot = ""
    if trend_plot_path:
        trend_plot = f"/static/plots/{os.path.basename(trend_plot_path)}?t={int(time.time())}"

    trend_views = empty_trend_views()
    for key, value in (report.get("trend_views") or {}).items():
        if key not in trend_views or not isinstance(value, dict):
            continue
        trend_views[key] = {
            "label": value.get("label", trend_views[key]["label"]),
            "points": value.get("points", []),
        }

    return {
        "heaviest": {
            "url": path_to_url(report.get("heaviest", {}).get("path", "")),
            "date": report.get("heaviest", {}).get("date", ""),
            "score": report.get("heaviest", {}).get("score", 0),
        },
        "lightest": {
            "url": path_to_url(report.get("lightest", {}).get("path", "")),
            "date": report.get("lightest", {}).get("date", ""),
            "score": report.get("lightest", {}).get("score", 0),
        },
        "trend_plot": trend_plot,
        "trend_views": trend_views,
    }

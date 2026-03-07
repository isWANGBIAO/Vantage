import json
import os
import time
import urllib.parse
from pathlib import Path


FACE_REPORT_CACHE_FILE = Path("history") / "face_report.json"


def save_face_report_cache(report: dict, report_file: str | Path = FACE_REPORT_CACHE_FILE) -> Path:
    path = Path(report_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_face_report_cache(report_file: str | Path = FACE_REPORT_CACHE_FILE) -> dict | None:
    path = Path(report_file)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


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
    }

"""System status, storage statistics, and trusted air-quality routes."""

from . import camera as _camera
from . import runtime as _runtime


from fastapi.responses import JSONResponse
from src.services.location_trust import LocationPurpose
from src.services.location_trust import LocationSample
from src.services.location_trust import LocationStatus
from src.services.location_trust import LocationTrustResolver
from typing import Optional
from pathlib import Path
import asyncio
from src.services.location_trust import browser_location_rejection
from src.services.location_trust import compare_browser_location
from datetime import datetime
from src.manager.get_location import get_trusted_location_sample_async
import os
import psutil
import requests
import shutil
from datetime import timezone
from fastapi import APIRouter

router = APIRouter()

_AQI_LOCATION_TRUST_RESOLVER = LocationTrustResolver()

def _build_status_payload():
    frame_diagnostics = _camera._build_camera_frame_diagnostics()
    return {
        "camera_online": _camera._camera_online(),
        "show_person_box": _runtime.state.show_person_box,
        "camera_frame_available": frame_diagnostics["available"],
        "camera_frame_dark": frame_diagnostics["dark"],
        "camera_frame_mean_luma": frame_diagnostics["mean_luma"],
        "paths": {
            "photo": bool(_runtime.state.paths.get("photo")),
            "screenshot": bool(_runtime.state.paths.get("screenshot")),
        },
        "media_roots_ready": {
            "photos": bool(_runtime.state.photos_path and os.path.exists(_runtime.state.photos_path)),
            "screenshots": bool(_runtime.state.screenshots_path and os.path.exists(_runtime.state.screenshots_path)),
        },
        "runtime": {
            "cwd_name": Path(os.getcwd()).name,
        },
    }

@router.get("/api/v1/system/status")
async def get_status():
    return _build_status_payload()

@router.get("/api/v1/system/statistics")
async def get_sys_stats():
    try:
        cpu_usage = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()

        # Use cached sizes from background thread (avoid blocking event loop)
        photos_size = _runtime.state.photos_size
        screenshots_size = _runtime.state.screenshots_size
        legacy_size = _runtime.state.legacy_size

        total, used, free = shutil.disk_usage(_runtime.state.photos_path or ".")

        return {
            "cpu_usage": cpu_usage,
            "memory_used_gb": round(memory.used / (1024**3), 2),
            "memory_total_gb": round(memory.total / (1024**3), 2),
            "memory_percent": memory.percent,
            "disk_free_gb": round(free / (1024**3), 2),
            "storage_used_mb": round((photos_size + screenshots_size + legacy_size) / (1024**2), 2),
            "storage_scan_truncated": _runtime.state.storage_scan_truncated,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/api/v1/system/air-quality")
async def get_aqi_stats(
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    accuracy: Optional[float] = None,
    timestamp_ms: Optional[float] = None,
):
    """Fetch current AQI (US) only when a current location is trusted."""
    target_lat = None
    target_lon = None
    city = "Location unavailable"

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
        browser_values = (lat, lon, accuracy, timestamp_ms)
        browser_metadata_present = any(value is not None for value in browser_values)
        browser_sample = None
        if browser_metadata_present and all(
            value is not None for value in browser_values
        ):
            try:
                if any(isinstance(value, bool) for value in browser_values):
                    raise ValueError("boolean browser location metadata")
                browser_sample = LocationSample(
                    latitude=float(lat),
                    longitude=float(lon),
                    accuracy_m=float(accuracy),
                    captured_at=datetime.fromtimestamp(
                        float(timestamp_ms) / 1_000,
                        tz=timezone.utc,
                    ),
                    source="browser",
                    is_remote_source=False,
                )
            except (OverflowError, OSError, TypeError, ValueError):
                browser_sample = None

        if browser_metadata_present:
            if browser_sample is None:
                return build_unavailable_payload()
            if browser_location_rejection(browser_sample) is not None:
                return build_unavailable_payload()

        try:
            backend_sample = await get_trusted_location_sample_async(
                LocationPurpose.AQI,
                resolver=_AQI_LOCATION_TRUST_RESOLVER,
            )
        except Exception:
            backend_sample = None

        if backend_sample is None:
            return build_unavailable_payload()

        if browser_metadata_present:
            browser_decision = compare_browser_location(
                browser_sample,
                backend_sample,
            )
            if (
                browser_decision.status is not LocationStatus.TRUSTED
                or browser_decision.sample is None
            ):
                return build_unavailable_payload()

        target_lat = backend_sample.latitude
        target_lon = backend_sample.longitude

        city = "Current Location"
        print("[AQI] Fetching for trusted current location")

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
        print("AQI Error: upstream request failed")
        return build_unavailable_payload(str(e))

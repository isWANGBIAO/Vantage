"""Narrow local report API; never exposes source photographs or checkpoint paths."""

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from src.backend import application

router = APIRouter(prefix="/api/v1/body-analysis", tags=["Body Analysis"])


def _service():
    return application.get_services().body_analysis


@router.get("/status")
async def status():
    service = _service()
    service.refresh_on_settings_change()
    return await asyncio.to_thread(service.status)


@router.get("/report")
async def report():
    result = await asyncio.to_thread(_service().report)
    if result is None:
        raise HTTPException(status_code=404, detail="Report unavailable.")
    return result


@router.get("/setup")
async def setup():
    """Read-only setup hints; directory values stay in the existing JSON settings API."""
    service = _service()
    state = await asyncio.to_thread(service.status)
    return {
        "enabled": state["enabled"],
        "environment": state["environment"],
        "last_report_available": state["last_report_available"],
    }


@router.post("/install", status_code=202)
async def install():
    service = _service()
    if not (await asyncio.to_thread(service.status))["enabled"]:
        raise HTTPException(status_code=409, detail="Body analysis is disabled.")
    if not await service.install():
        raise HTTPException(status_code=409, detail="Body analysis is already busy.")
    return await asyncio.to_thread(service.status)


@router.post("/retry", status_code=202)
async def retry():
    service = _service()
    if not (await asyncio.to_thread(service.status))["enabled"]:
        raise HTTPException(status_code=409, detail="Body analysis is disabled.")
    if not service.start(force=True):
        raise HTTPException(status_code=409, detail="Body analysis is already busy.")
    return await asyncio.to_thread(service.status)


@router.get("/assets/{relative:path}")
async def asset(relative: str):
    path = await asyncio.to_thread(_service().asset, relative)
    if path is None:
        raise HTTPException(status_code=404, detail="Asset unavailable.")
    return FileResponse(path, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

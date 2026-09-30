"""Application composition for UI-independent jobs, scheduling and API discovery.

The services contain no HTTP/Electron code. These adapters connect the existing
domain functions to services once per backend process/lifespan.
"""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.backend.api_contracts import (
    API_VERSION,
    ActionPlanJob,
    ActionPlanJobRequest,
    ActionPlanJobs,
    BackendCapabilities,
    ActionPlanStreamEvent,
    SchedulerState,
)
from src.backend.responses import NDJSONResponse, ndjson_openapi
from src.core.config import Config
from src.core.user_config import load_settings
from src.services.action_plan_jobs import ActionPlanJobService
from src.services.action_plan_scheduler import ActionPlanScheduler
from src.services.action_plan_store import ActionPlanStore
from src.services.automation_catalog import OPERATIONS


async def _read_today():
    from src.backend import action_plans
    return await action_plans.get_today_action_plan()


async def _read_revision():
    from src.backend import action_plans
    return await asyncio.to_thread(action_plans._compute_action_plan_source_revision)


async def _generate(request):
    from src.backend import action_plans

    store = ActionPlanStore(Config.get_history_dir())
    pending = await asyncio.to_thread(store.begin)
    iterator = None
    try:
        parameters = {**request, "replace_today": False}
        response = await action_plans.create_action_plan_stream(
            action_plans.ActionPlanRequest(**parameters), staging_directory=pending.directory,
        )
        iterator = response.body_iterator
        completed = False
        failed = False
        async for event in iterator:
            decoded = json.loads(event)
            if decoded.get("error") or str(decoded.get("log", "")).startswith(
                ("STREAM_ANALYSIS_ERROR:", "STREAM_PLAN_ERROR:", "STREAM_ERROR:")
            ):
                failed = True
            if decoded.get("done") is True:
                completed = True
            else:
                yield event
        if completed and not failed:
            # Cancellation is checked before publication. There is deliberately
            # no await inside this small local-file commit, so cancellation can
            # never abandon a worker that later publishes a cancelled job.
            published = store.publish(pending, replace_today=bool(request.get("replace_today")))
            if not published.context_updated:
                yield {"log": "Plan saved; chat context could not be fully refreshed."}
            yield {"done": True}
    finally:
        try:
            if iterator is not None:
                await iterator.aclose()
        finally:
            store.discard(pending)


@dataclass
class ApplicationServices:
    jobs: ActionPlanJobService
    scheduler: ActionPlanScheduler


_services: ApplicationServices | None = None


def get_services() -> ApplicationServices:
    global _services
    if _services is None:
        jobs = ActionPlanJobService(_generate, _read_today, _read_revision)
        scheduler = ActionPlanScheduler(
            jobs, load_settings, _read_today, _read_revision,
            Path(Config.get_runtime_dir()) / "action-plan-scheduler.json",
        )
        _services = ApplicationServices(jobs, scheduler)
    return _services


async def start():
    get_services().scheduler.start()


async def stop():
    global _services
    services, _services = _services, None
    if services is not None:
        await services.scheduler.close()
        await services.jobs.close()


def _job_or_404(job_id):
    try:
        return get_services().jobs.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found or no longer retained.") from None


async def _event_stream(job_id, after=0):
    async for event in get_services().jobs.iterate_events(job_id, after=after):
        yield json.dumps(event, ensure_ascii=False) + "\n"


def build_router():
    router = APIRouter(tags=["Application API v1"])

    @router.get("/api/v1/capabilities", response_model=BackendCapabilities)
    async def capabilities():
        return BackendCapabilities(
            capabilities=["settings", "onboarding", "action-plan-jobs", "action-plan-scheduler",
                          "ndjson-events", "operation-catalog", "openapi"],
            platform_owned=["window", "tray", "login-startup", "file-picker", "camera-permission",
                            "clipboard", "system-locale"],
        )

    @router.get("/api/v1/operations")
    async def operations():
        return {"api_version": API_VERSION, "operations": [
            {"name": op.name, "description": op.description, "method": op.method,
             "path": op.path, "input_schema": op.input_schema, "output_kind": op.output_kind,
             "availability": op.availability, "mutation": op.mutation,
             "sensitive": op.sensitive, "side_effect": op.side_effect,
             "required_headers": op.required_headers,
             "unavailable_reason": op.unavailable_reason}
            for op in OPERATIONS
        ]}

    @router.post("/api/v1/action-plan/jobs", response_model=ActionPlanJob, status_code=202)
    async def create_job(request: ActionPlanJobRequest):
        return await get_services().jobs.start(request.model_dump(), trigger="manual")

    @router.get("/api/v1/action-plan/jobs", response_model=ActionPlanJobs)
    async def list_jobs():
        jobs = get_services().jobs
        return {"jobs": jobs.list_jobs(), "active": jobs.active()}

    @router.get("/api/v1/action-plan/jobs/{job_id}", response_model=ActionPlanJob)
    async def read_job(job_id: str):
        return _job_or_404(job_id)

    @router.get("/api/v1/action-plan/jobs/{job_id}/events", response_class=NDJSONResponse,
                responses={200: {"model": ActionPlanStreamEvent, "description": "UTF-8 NDJSON; one typed event per line."}},
                openapi_extra=ndjson_openapi(ActionPlanStreamEvent))
    async def read_events(job_id: str, after: int = Query(default=0, ge=0)):
        _job_or_404(job_id)
        return StreamingResponse(_event_stream(job_id, after), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store"})

    @router.post("/api/v1/action-plan/jobs/{job_id}/cancel", response_model=ActionPlanJob)
    async def cancel_job(job_id: str):
        _job_or_404(job_id)
        return await get_services().jobs.cancel(job_id)

    @router.get("/api/v1/action-plan/scheduler", response_model=SchedulerState)
    async def scheduler_state():
        return get_services().scheduler.status()


    return router

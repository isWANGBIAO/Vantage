"""Exercise the real HTTP contract with injected, non-network domain adapters."""
import asyncio
import json
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from src.backend import application
from src.services.action_plan_jobs import ActionPlanJobService


def test_jobs_http_deduplicates_survives_observer_disconnect_and_exposes_result(monkeypatch):
    async def run():
        release = asyncio.Event()
        saved = {"exists": False}
        calls = []

        async def generate(request):
            calls.append(request)
            yield {"log": "STREAM_ANALYSIS_START:"}
            await release.wait()
            saved.update(exists=True, id="new", analysis={"body": "analysis"}, plan={"body": "plan"})
            yield {"done": True}

        async def today():
            return dict(saved)

        jobs = ActionPlanJobService(generate, today, lambda: "revision")
        services = SimpleNamespace(jobs=jobs, scheduler=SimpleNamespace(status=lambda: {"running": True}))
        monkeypatch.setattr(application, "get_services", lambda: services)
        app = FastAPI()
        app.include_router(application.build_router())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
            first = await client.post("/api/v1/action-plan/jobs", json={"replace_today": True})
            assert first.status_code == 202
            job_id = first.json()["id"]
            second = await client.post("/api/v1/action-plan/jobs", json={})
            assert second.json()["id"] == job_id and second.json()["reused"] is True
            assert (await client.get("/api/v1/action-plan/jobs")).json()["active"]["id"] == job_id
            # No observer is attached. The backend still finishes the job.
            release.set()
            result = await jobs.wait(job_id)
            assert result["status"] == "succeeded" and len(calls) == 1
            fetched = (await client.get(f"/api/v1/action-plan/jobs/{job_id}")).json()
            assert fetched["result"]["analysis"]["body"] == "analysis"
            events = await client.get(f"/api/v1/action-plan/jobs/{job_id}/events")
            lines = [json.loads(line) for line in events.text.splitlines()]
            assert any(line.get("done") is True for line in lines)
            assert (await client.get("/api/v1/action-plan/jobs/missing")).status_code == 404
            assert (await client.get(f"/api/v1/action-plan/jobs/{job_id}/events?after=-1")).status_code == 422
            assert (await client.post("/api/v1/action-plan/jobs", json={"api_key": "unexpected"})).status_code == 422
            capabilities = (await client.get("/api/v1/capabilities")).json()
            assert capabilities["api_version"] == "1.0"
            schema = (await client.get("/openapi.json")).json()
            assert "ActionPlanJob" in schema["components"]["schemas"]
        await jobs.close()
    asyncio.run(run())


def test_legacy_stream_shares_job_service_and_explicit_cancel_cleans_up(monkeypatch):
    async def run():
        entered = asyncio.Event()
        cleaned = asyncio.Event()

        async def generate(_request):
            try:
                entered.set()
                yield {"log": "progress"}
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        jobs = ActionPlanJobService(generate, lambda: {"exists": False})
        monkeypatch.setattr(application, "get_services", lambda: SimpleNamespace(jobs=jobs))
        app = FastAPI()
        app.include_router(application.build_router())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
            request = asyncio.create_task(client.post("/api/action_plan", json={}))
            await entered.wait()
            job_id = jobs.active()["id"]
            response = await client.post(f"/api/v1/action-plan/jobs/{job_id}/cancel")
            assert response.json()["status"] == "cancelled"
            assert cleaned.is_set()
            legacy = await request
            assert legacy.headers["x-vantage-job-id"] == job_id
            assert not any(json.loads(line).get("done") for line in legacy.text.splitlines())
        await jobs.close()
    asyncio.run(run())

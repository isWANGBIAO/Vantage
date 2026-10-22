import asyncio
import threading

import httpx
from fastapi import FastAPI

from src.backend import plots
from src.services import plot_dashboard


def test_refresh_invalidates_old_inflight_cache_writer(monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []
    old = {"charts": [{"id": "sleep-schedule", "empty": True, "error": "synthetic transient lock"}], "count": 1}
    fresh = {"charts": [{"id": "sleep-schedule", "empty": False}], "count": 1}

    def build():
        calls.append(True)
        if len(calls) == 1:
            started.set()
            assert release.wait(10)
            return old
        return fresh

    plots._clear_plot_dashboard_cache()
    monkeypatch.setattr(plots, "_get_plot_dashboard_cache_key", lambda: (("synthetic", 1, 1),))
    monkeypatch.setattr(plot_dashboard, "build_plot_dashboard_data", build)
    app = FastAPI()
    app.include_router(plots.router)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            pending = asyncio.create_task(client.get("/api/v1/plots/data"))
            try:
                assert await asyncio.to_thread(started.wait, 5)
                assert (await client.post("/api/v1/plots/refresh")).status_code == 200
                assert (await client.get("/api/v1/plots/data")).json() == fresh
            finally:
                release.set()
            assert (await pending).json() == old
            assert (await client.get("/api/v1/plots/data")).json() == fresh
            assert len(calls) == 2

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        plots._clear_plot_dashboard_cache()

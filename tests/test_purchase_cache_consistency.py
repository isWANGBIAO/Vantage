"""Synthetic HTTP regressions for recommendation result-cache identity and races."""

import asyncio
import json
import threading
from pathlib import Path

import httpx
import pandas as pd
import pytest
from fastapi import FastAPI

from src.backend import finance_recommendations as recommendations


def context_at(time, data="unchanged", calendar="weekday"):
    return f'## Time Series Data (JSON)\n\n{data}\n\n## Runtime Context\n\n' + json.dumps({
        "current_time": time, "calendar": calendar,
    }, separators=(",", ":"))


@pytest.fixture
def purchase_api(tmp_path, monkeypatch):
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(recommendations.Config, "get_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(recommendations.Config, "get_history_dir", lambda: tmp_path / "history")
    monkeypatch.setattr(recommendations.DataLoader, "resolve_data_path", lambda _: Path("Balance Sheet.xlsx"))
    monkeypatch.setattr(recommendations.DataLoader, "load_excel_sheets", lambda _: {
        "Assets": pd.DataFrame({"Name": ["Synthetic asset"], "Amount": [100]}),
    })
    clock = ["2026-01-01 11:00"]
    monkeypatch.setattr(recommendations, "_build_purchase_context_prompt", lambda _: context_at(clock[0]))
    calls = []
    entered = threading.Event()
    release = threading.Event()
    block = [False]

    class FakeClient:
        def chat(self, **kwargs):
            calls.append(kwargs)
            if block[0] and len(calls) == 1:
                entered.set()
                assert release.wait(10), "Synthetic model request was not released"
            mode = kwargs["metadata"]["purchase_recommendation_mode"]
            count = kwargs["metadata"]["purchase_recommendation_count"]
            return {"content": json.dumps({"recommendation_groups": [{
                "key": "practical", "title": "Synthetic practical",
                "items": [{"name": f"{mode}-{index}"} for index in range(count)],
            }]}), "model": "synthetic-model"}

    monkeypatch.setattr(recommendations, "LLMClient", FakeClient)
    app = FastAPI()
    app.include_router(recommendations.router)
    return app, clock, calls, entered, release, block


def test_minute_tick_reuses_real_disk_cache_but_next_day_does_not(purchase_api):
    app, clock, calls, *_ = purchase_api

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = (await client.get("/api/v1/finance/purchase-recommendations?recommendation_count=6")).json()
            clock[0] = "2026-01-01 11:01"
            second = (await client.get("/api/v1/finance/purchase-recommendations?recommendation_count=6")).json()
            assert second["from_cache"] is True
            assert first["cache_key"] == second["cache_key"]
            assert len(calls) == 2
            clock[0] = "2026-01-02 11:01"
            third = (await client.get("/api/v1/finance/purchase-recommendations?recommendation_count=6")).json()
            assert third["from_cache"] is False
            assert third["cache_key"] != first["cache_key"]
            assert len(calls) == 4
            forced = (await client.post("/api/v1/finance/purchase-recommendations/regenerate", json={"recommendation_count": 6})).json()
            assert forced["from_cache"] is False
            assert len(calls) == 6

    asyncio.run(scenario())


def test_dismissal_during_generation_is_applied_to_final_http_response(purchase_api):
    app, _, _, entered, release, block = purchase_api
    block[0] = True

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            pending = asyncio.create_task(client.post(
                "/api/v1/finance/purchase-recommendations/regenerate", json={"recommendation_count": 6},
            ))
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                dismissed = await client.post("/api/v1/finance/purchase-recommendations/dismiss", json={
                    "cache_key": "previous-cache", "group_key": "practical", "item": {"name": "contextual-0"},
                })
                assert dismissed.status_code == 200
                assert dismissed.json()["count"] == 1
            finally:
                release.set()
            response = await asyncio.wait_for(pending, 5)
            assert response.status_code == 200
            payload = response.json()
            names = [item["name"] for group in payload["recommendation_groups"] for item in group["items"]]
            assert "contextual-0" not in names
            assert payload["dismissed_count"] == 1
            assert payload["recommendation_count_actual"] == 5

    asyncio.run(scenario())


@pytest.mark.parametrize("changed", [
    context_at("2026-01-02 11:00"),
    context_at("2026-01-01 11:00", data="workbook changed"),
    context_at("2026-01-01 11:00", calendar="holiday"),
    "private prompt changed\n" + context_at("2026-01-01 11:00"),
    context_at("unknown runtime format"),
])
def test_result_cache_still_invalidates_material_context_changes(changed):
    original = recommendations._build_purchase_context_metadata(context_at("2026-01-01 11:00"))
    updated = recommendations._build_purchase_context_metadata(changed)
    assert original["cache_context_hash"] != updated["cache_context_hash"]


def test_cache_normalization_preserves_exact_prompt_hash_and_does_not_mask_user_text():
    first = recommendations._build_purchase_context_metadata(context_at("2026-01-01 11:00"))
    second = recommendations._build_purchase_context_metadata(context_at("2026-01-01 11:01"))
    assert first["prompt_hash"] != second["prompt_hash"]
    assert first["cache_context_hash"] == second["cache_context_hash"]
    assert recommendations._build_purchase_context_metadata('User current_time="11:00"')["cache_context_hash"] != recommendations._build_purchase_context_metadata('User current_time="11:01"')["cache_context_hash"]

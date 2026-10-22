"""Real DTO/CLI integration boundaries with isolated synthetic records only."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_usage_integrity import test_two_round_cli_accepts_nullable_ledger_summary as exercise_two_round
from tests.test_model_resolution_boundaries import provider_runtime as provider_runtime
from src.backend import chat, providers, settings, action_plans
from src.backend.api_contracts import ChatStreamEvent


def test_model_only_real_child_retains_route_metadata_and_nullable_usage_dto(provider_runtime):
    configure, observed = provider_runtime
    configure([("primary", "default-model"), ("secondary", "Pro/target-model")])
    app = FastAPI()
    app.include_router(chat.router)
    app.include_router(providers.router)
    app.include_router(settings.router)
    with TestClient(app) as api:
        response = api.post("/api/v1/chat", json={"message": "--help", "model": "target-model"})
        assert response.status_code == 200
        events = [json.loads(line) for line in response.text.splitlines()]
        for event in events:
            ChatStreamEvent.model_validate(event)
        stats = [json.loads(event["log"].removeprefix("STATS_JSON:")) for event in events
                 if event.get("log", "").startswith("STATS_JSON:")][-1]
        assert stats["provider_route"] == stats["requested_provider_route"] == "secondary"
        assert stats["model"] == "Pro/target-model"
        assert stats["requested_model"] == "target-model"
        assert stats["fallback_used"] is False
        assert stats["total_tokens"] is None
        assert stats["usage_complete"] is False
        context = api.get("/api/v1/chat/context").json()
        assert context["preferred_model"] == "target-model"  # Preserve the requested alias as a preference.
        assert context["preferred_provider_route"] == "secondary"
        assert context["stats"]["total_tokens"] is None
        assert context["stats"]["usage_complete"] is False
    assert len(observed) == 1
    assert observed[0][0] == "/secondary/v1/chat/completions"


def test_exact_profile_survives_settings_dto_and_matches_catalog(provider_runtime):
    configure, _ = provider_runtime
    configure([("primary", "Qwen3.8-27B")], model_profiles={"qwen3.8-27b": {
        "parameters": {"temperature": 0.23}, "reasoning_tiers": ["low", "high"],
        "reasoning_aliases": {"xhigh": "high"},
    }})
    app = FastAPI()
    app.include_router(settings.router)
    app.include_router(providers.router)
    with TestClient(app) as api:
        state = api.get("/api/v1/settings")
        assert state.status_code == 200
        profile = state.json()["provider"]["model_profiles"]["qwen3.8-27b"]
        assert profile["parameters"]["temperature"] == 0.23
        assert profile["reasoning_tiers"] == ["low", "high"]
        assert profile["reasoning_aliases"] == {"xhigh": "high"}
        option = api.get("/api/v1/models").json()["model_options"][0]
        assert option["reasoning_tiers"] == profile["reasoning_tiers"]
        assert option["reasoning_aliases"] == profile["reasoning_aliases"]


def test_two_round_saved_result_http_dto_preserves_unknown_stats(tmp_path, monkeypatch, capsys):
    exercise_two_round(tmp_path, monkeypatch, capsys, None, False)
    app = FastAPI()
    app.include_router(action_plans.router)
    with TestClient(app) as api:
        response = api.get("/api/v1/action-plan/today")
    assert response.status_code == 200
    result = response.json()
    assert result["exists"] is True
    assert result["analysis"]["body"] == "synthetic round 1"
    assert result["plan"]["body"] == "synthetic round 2"
    assert result["meta"]["stats"]["total_tokens"] is None
    assert result["meta"]["stats"]["usage_complete"] is False

"""Provider SDK/network and config work must not block the HTTP event loop."""
import asyncio
import threading

import pytest

from src.backend import providers


@pytest.mark.parametrize("kind", ["llm", "special"])
def test_model_discovery_runs_on_worker_thread(monkeypatch, kind):
    loop_thread = threading.get_ident()
    calls = []
    resolved = {
        "route": "test", "base_url": "http://127.0.0.1:8317/v1",
        "api_key": "test-only-placeholder", "type": "openai-compatible",
        "kind": "voice", "mode": "custom",
    }

    def resolve(*args, **kwargs):
        calls.append(("config", threading.get_ident()))
        return resolved

    def discover(**kwargs):
        calls.append(("network", threading.get_ident()))
        return {"models": ["test-model"], "model_capabilities": {}}

    monkeypatch.setattr(providers, "_resolve_discover_secret", resolve)
    monkeypatch.setattr(providers, "_resolve_special_provider_config", resolve)
    monkeypatch.setattr(providers.LLMClient, "discover_models_for_config", discover)
    if kind == "llm":
        response = asyncio.run(providers.discover_llm_models(providers.LLMModelDiscoverRequest()))
    else:
        response = asyncio.run(providers.discover_provider_models(providers.ProviderModelDiscoverRequest(kind="voice")))
    assert response["models"] == ["test-model"]
    assert [call[0] for call in calls] == ["config", "network"]
    assert all(thread_id != loop_thread for _, thread_id in calls)


def test_model_catalog_runs_on_worker_thread(monkeypatch):
    loop_thread = threading.get_ident()
    threads = []

    def build_payload():
        threads.append(threading.get_ident())
        return {"models": []}

    monkeypatch.setattr(providers, "_build_llm_models_payload", build_payload)
    assert asyncio.run(providers.list_llm_models()) == {"models": []}
    assert len(threads) == 1
    assert threads[0] != loop_thread

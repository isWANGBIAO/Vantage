"""Masked provider secrets stay bound to their saved API destination."""
import asyncio
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from src.backend import providers
from src.backend.security import LoopbackAccessMiddleware


@pytest.fixture
def saved_provider(monkeypatch):
    entry = {"api_key": "synthetic-saved-secret", "base_url": "https://provider.invalid/v1", "model": "synthetic"}
    monkeypatch.setattr(providers, "load_provider_config", lambda: {"providers": {"test": entry}})
    return entry


@pytest.mark.parametrize("base_url", [None, "", "https://provider.invalid/v1/", "https://PROVIDER.invalid:443/v1"])
@pytest.mark.parametrize("api_key", [None, "", "********"])
def test_ai_discovery_reuses_saved_key_only_at_same_api_base(saved_provider, base_url, api_key):
    result = providers._resolve_discover_secret(providers.LLMModelDiscoverRequest(
        route="test", base_url=base_url, api_key=api_key,
    ))
    assert result["api_key"] == saved_provider["api_key"]


@pytest.mark.parametrize("base_url", [
    "https://other.invalid/v1", "http://provider.invalid/v1", "https://provider.invalid:444/v1",
    "https://provider.invalid/v2", "https://provider.invalid/v1?redirect=other",
    "https://provider.invalid@other.invalid/v1", "https://provider.invalid:0/v1",
    "https://provider.invalid/v\n1", "https://provider.invalid/v1#fragment",
])
@pytest.mark.parametrize("api_key", [None, "********"])
def test_ai_discovery_does_not_reuse_key_at_another_api_base(saved_provider, base_url, api_key):
    result = providers._resolve_discover_secret(providers.LLMModelDiscoverRequest(
        route="test", base_url=base_url, api_key=api_key,
    ))
    assert not result["api_key"]


def test_explicit_key_can_be_used_at_explicit_new_destination(saved_provider):
    result = providers._resolve_discover_secret(providers.LLMModelDiscoverRequest(
        route="test", base_url="https://new.invalid/v1", api_key="synthetic-new-secret",
    ))
    assert result["api_key"] == "synthetic-new-secret"
    assert result["base_url"] == "https://new.invalid/v1"


@pytest.mark.parametrize("kind", ["voice", "image"])
@pytest.mark.parametrize("submitted_key", [None, "********"])
def test_custom_special_provider_key_is_bound_to_saved_destination(monkeypatch, kind, submitted_key):
    monkeypatch.setattr(providers, "load_settings", lambda: {
        f"{kind}_provider_mode": "custom", f"{kind}_base_url": "https://saved.invalid/v1",
        f"{kind}_api_key": "synthetic-saved-secret", f"{kind}_model": "synthetic",
    })
    changed = providers._resolve_special_provider_config(
        kind=kind, mode="custom", base_url="https://new.invalid/v1", api_key=submitted_key,
    )
    assert changed["api_key"] == ""
    assert f"{kind}_api_key" in changed["missing"]
    same = providers._resolve_special_provider_config(kind=kind, base_url="https://saved.invalid/v1/")
    assert same["api_key"] == "synthetic-saved-secret"
    explicit = providers._resolve_special_provider_config(
        kind=kind, base_url="https://new.invalid/v1", api_key="synthetic-new-secret",
    )
    assert explicit["api_key"] == "synthetic-new-secret"


def test_discovery_destination_override_never_reaches_network_with_saved_key(monkeypatch, saved_provider):
    network = Mock(side_effect=AssertionError("Network must not be reached"))
    monkeypatch.setattr(providers.LLMClient, "_discover_primary_models", network)
    app = FastAPI()
    app.add_middleware(LoopbackAccessMiddleware)
    app.include_router(providers.router)

    async def exercise():
        transport = httpx.ASGITransport(app, client=("127.0.0.1", 12345))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            result = await client.post("/api/v1/models/discover", json={
                "route": "test", "base_url": "https://new.invalid/v1", "api_key": "********",
            })
            assert result.status_code == 400
            assert saved_provider["api_key"] not in result.text
            assert "API Key is required" in result.json()["error"]
            result = await client.post("/api/v1/models/discover", headers={"Origin": "https://new.invalid"}, json={
                "route": "test", "base_url": "https://new.invalid/v1",
            })
            assert result.status_code == 403
    asyncio.run(exercise())
    network.assert_not_called()

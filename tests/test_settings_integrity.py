"""Strict, non-destructive settings HTTP contracts using synthetic configuration."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend import settings
from src.core.config import Config
from src.services.automation_catalog import get_operation
from src.services.vantage_client import ArgumentValidationError, _validate_schema


@pytest.fixture
def settings_http(tmp_path, monkeypatch):
    for method, directory in {
        "get_data_dir": "data", "get_config_dir": "config", "get_history_dir": "history",
        "get_logs_dir": "logs", "get_plot_dir": "plots", "get_cache_dir": "cache",
        "get_runtime_dir": "runtime", "get_migration_dir": "migration", "get_project_root": "project",
    }.items():
        monkeypatch.setattr(Config, method, staticmethod(lambda directory=directory: tmp_path / directory))
    app = FastAPI()
    app.include_router(settings.router)
    with TestClient(app, raise_server_exceptions=False) as http:
        initial = http.put("/api/v1/settings", json={"action_plan_auto_generate": False, "provider_config": {
            "selected_provider": "primary", "providers": {"primary": {
                "api_key": "synthetic-key", "base_url": "https://example.invalid/v1", "enabled": False,
            }},
        }})
        assert initial.status_code == 200, initial.text
        yield http, tmp_path / "config"


@pytest.mark.parametrize("payload", [
    {"action_plan_auto_generate": "false"}, {"launch_at_login": 1},
    {"display_language": []}, {"display_language": "invalid"}, {"theme": {}},
    {"theme_mode": "invalid"}, {"voice_provider_mode": "invalid"}, {"voice_base_url": []},
    {"voice_models": [1]}, {"voice_last_refreshed_at": True},
    {"provider_config": {"selected_provider": []}},
    {"provider_config": {"providers": {"primary": {"enabled": "false"}}}},
    {"provider_config": {"providers": {"primary": {"api_key": 123}}}},
    {"provider_config": {"providers": {"primary": {"context_window_tokens": True}}}},
    {"provider_config": {"providers": {"primary": {"max_output_tokens": 0}}}},
    {"provider_config": {"providers": {"primary": {"type": "unsupported"}}}},
    {"provider_config": {"providers": {"primary": {"models": [None]}}}},
    {"provider_config": {"providers": {"primary": {"unexpected": "ignored-before"}}}},
])
def test_settings_http_rejects_the_same_invalid_types_as_cli_mcp_without_writing(settings_http, payload):
    http, root = settings_http
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    with pytest.raises(ArgumentValidationError):
        _validate_schema(payload, get_operation("settings.update").input_schema)
    response = http.put("/api/v1/settings", json=payload)
    assert response.status_code == 422, response.text
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before


@pytest.mark.parametrize("value", [[], {}, None, "invalid", True])
def test_display_language_http_uses_its_catalog_contract_before_writing(settings_http, value):
    http, root = settings_http
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    response = http.put("/api/v1/settings/display-language", json={"display_language": value})
    assert response.status_code == 422, response.text
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before


def test_route_rename_cannot_save_a_mask_as_if_it_were_a_new_routes_credential(settings_http):
    http, root = settings_http
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    response = http.put("/api/v1/settings", json={"provider_config": {
        "selected_provider": "renamed", "providers": {"renamed": {
            "api_key": "********", "base_url": "https://example.invalid/v1", "enabled": True,
        }},
    }})
    assert response.status_code == 422, response.text
    assert "explicit API key" in response.json()["detail"]
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before


@pytest.mark.parametrize("key", ["synthetic-new-key", ""])
def test_route_rename_allows_explicit_new_or_explicitly_cleared_credentials(settings_http, key):
    http, root = settings_http
    response = http.put("/api/v1/settings", json={"provider_config": {
        "selected_provider": "renamed", "providers": {"renamed": {
            "api_key": key, "base_url": "https://example.invalid/v1", "enabled": True,
        }},
    }})
    assert response.status_code == 200, response.text
    import json
    saved = json.loads((root / "providers.json").read_text(encoding="utf-8"))
    assert set(saved["providers"]) == {"renamed"}
    assert saved["providers"]["renamed"]["api_key"] == key

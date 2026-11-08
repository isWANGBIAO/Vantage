"""Sleep-chart preferences share the canonical settings JSON and API contract."""

import json

import pytest
from fastapi import HTTPException

from src.backend import settings as backend_settings
from src.core import user_config
from src.services.automation_catalog import get_operation
from src.services.vantage_client import ArgumentValidationError, _validate_schema
from tests.test_settings_automation_endpoint import _use_runtime_dirs


@pytest.mark.parametrize("mode", user_config.SLEEP_CHART_MODES)
def test_sleep_mode_json_round_trip_and_partial_api_saves(tmp_path, monkeypatch, mode):
    paths = _use_runtime_dirs(monkeypatch, tmp_path)
    assert backend_settings.get_automation_settings()["settings"]["sleep_chart_mode"] == "segments"
    updated = backend_settings.update_automation_settings({"sleep_chart_mode": mode})
    assert updated["settings"]["sleep_chart_mode"] == mode
    backend_settings.update_automation_settings({"theme": "light"})
    assert user_config.load_settings()["sleep_chart_mode"] == mode
    persisted = json.loads((paths["config"] / "settings.json").read_text(encoding="utf-8"))
    assert persisted["sleep_chart_mode"] == mode
    assert persisted["theme"] == "light"


@pytest.mark.parametrize("value", [None, True, 0, "", "weekly", [], {}])
def test_sleep_mode_invalid_write_fails_before_changing_files(tmp_path, monkeypatch, value):
    paths = _use_runtime_dirs(monkeypatch, tmp_path)
    user_config.save_settings({"sleep_chart_mode": "rolling"})
    settings_file = paths["config"] / "settings.json"
    before = settings_file.read_bytes()
    with pytest.raises(HTTPException) as error:
        backend_settings.update_automation_settings({"sleep_chart_mode": value, "theme": "light"})
    assert error.value.status_code == 422
    assert settings_file.read_bytes() == before
    with pytest.raises(ValueError, match="sleep_chart_mode"):
        user_config.save_settings({"sleep_chart_mode": value}, settings_file)
    assert settings_file.read_bytes() == before


@pytest.mark.parametrize("value", [None, True, "weekly", [], {}])
def test_sleep_mode_invalid_or_missing_legacy_value_repairs_to_default(tmp_path, value):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"sleep_chart_mode": value, "theme": "light"}), encoding="utf-8")
    settings = user_config.load_settings(settings_file)
    assert settings["sleep_chart_mode"] == "segments"
    assert settings["theme"] == "light"
    assert json.loads(settings_file.read_text(encoding="utf-8"))["sleep_chart_mode"] == "segments"
    settings_file.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    assert user_config.load_settings(settings_file)["sleep_chart_mode"] == "segments"


def test_sleep_mode_cli_mcp_schema_uses_exact_canonical_enum():
    schema = get_operation("settings.update").input_schema
    assert tuple(schema["properties"]["sleep_chart_mode"]["enum"]) == user_config.SLEEP_CHART_MODES
    for mode in user_config.SLEEP_CHART_MODES:
        _validate_schema({"sleep_chart_mode": mode}, schema)
    for invalid in ("weekly", None, True):
        with pytest.raises(ArgumentValidationError):
            _validate_schema({"sleep_chart_mode": invalid}, schema)

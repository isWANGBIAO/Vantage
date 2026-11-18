"""Chinese typography is an explicit shared setting, not an OS language guess."""

import json

import pytest
from fastapi import HTTPException

from src.backend import settings as backend_settings
from src.core import user_config
from src.services.automation_catalog import get_operation
from src.services.vantage_client import ArgumentValidationError, _validate_schema
from tests.test_settings_automation_endpoint import _use_runtime_dirs


@pytest.mark.parametrize("font", user_config.CHINESE_FONT_FAMILIES)
def test_font_json_round_trip_and_partial_saves(tmp_path, monkeypatch, font):
    paths = _use_runtime_dirs(monkeypatch, tmp_path)
    assert backend_settings.get_automation_settings()["settings"]["chinese_font_family"] == "microsoft-yahei"
    updated = backend_settings.update_automation_settings({"chinese_font_family": font})
    assert updated["settings"]["chinese_font_family"] == font
    backend_settings.update_automation_settings({"theme": "light", "display_language": "en-US"})
    assert user_config.load_settings()["chinese_font_family"] == font
    saved = json.loads((paths["config"] / "settings.json").read_text(encoding="utf-8"))
    assert saved["chinese_font_family"] == font
    assert saved["display_language"] == "en-US"


@pytest.mark.parametrize("invalid", [None, True, 0, "", "system", "Arial", [], {}])
def test_font_invalid_save_does_not_change_file(tmp_path, monkeypatch, invalid):
    paths = _use_runtime_dirs(monkeypatch, tmp_path)
    user_config.save_settings({"chinese_font_family": "noto-sans-sc"})
    target = paths["config"] / "settings.json"
    before = target.read_bytes()
    with pytest.raises(HTTPException) as error:
        backend_settings.update_automation_settings({"chinese_font_family": invalid, "theme": "light"})
    assert error.value.status_code == 422
    assert target.read_bytes() == before
    with pytest.raises(ValueError, match="chinese_font_family"):
        user_config.save_settings({"chinese_font_family": invalid}, target)
    assert target.read_bytes() == before


@pytest.mark.parametrize("value", [None, True, "system", [], {}])
def test_font_legacy_invalid_value_repairs_to_default(tmp_path, value):
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({"chinese_font_family": value, "display_language": "en-US"}), encoding="utf-8")
    state = user_config.load_settings(target)
    assert state["chinese_font_family"] == "microsoft-yahei"
    assert state["display_language"] == "en-US"


def test_font_cli_mcp_schema_matches_settings_contract():
    schema = get_operation("settings.update").input_schema
    assert tuple(schema["properties"]["chinese_font_family"]["enum"]) == user_config.CHINESE_FONT_FAMILIES
    for font in user_config.CHINESE_FONT_FAMILIES:
        _validate_schema({"chinese_font_family": font}, schema)
    with pytest.raises(ArgumentValidationError):
        _validate_schema({"chinese_font_family": "system"}, schema)

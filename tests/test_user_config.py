import importlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

from src.core.config import Config


def _load_user_config_module():
    spec = importlib.util.find_spec("src.core.user_config")
    assert spec is not None, "src.core.user_config module should exist for persisted user config models"
    return importlib.import_module("src.core.user_config")


def test_load_settings_creates_default_settings_file(tmp_path):
    user_config = _load_user_config_module()
    config_dir = tmp_path / "config"

    with patch.object(Config, "get_config_dir", return_value=config_dir):
        payload = user_config.load_settings()

    expected = {
        "version": 1,
        "onboarding_completed": False,
        "launch_at_login": False,
        "display_language": "system",
        "theme": "dark",
        "background_mode": "balanced",
    }
    assert payload == expected
    assert json.loads((config_dir / "settings.json").read_text(encoding="utf-8")) == expected


def test_load_provider_config_heals_invalid_fields(tmp_path):
    user_config = _load_user_config_module()
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    providers_file = config_dir / "providers.json"
    providers_file.write_text(
        json.dumps(
            {
                "version": "bad",
                "selected_provider": 123,
                "providers": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = user_config.load_provider_config(providers_file=providers_file)

    expected = {
        "version": 1,
        "selected_provider": None,
        "providers": {},
    }
    assert payload == expected
    assert json.loads(providers_file.read_text(encoding="utf-8")) == expected


def test_load_migration_state_repairs_corrupt_json_in_migration_dir(tmp_path):
    user_config = _load_user_config_module()
    migration_dir = tmp_path / "migration"

    with patch.object(Config, "get_migration_dir", return_value=migration_dir):
        migration_file = migration_dir / "migration-state.json"
        migration_dir.mkdir(parents=True, exist_ok=True)
        migration_file.write_text("{not-json", encoding="utf-8")

        payload = user_config.load_migration_state()

    expected = {
        "version": 1,
        "completed": False,
        "source_path": None,
        "imported_at": None,
    }
    assert payload == expected
    assert json.loads(migration_file.read_text(encoding="utf-8")) == expected


def test_save_settings_normalizes_partial_payload(tmp_path):
    user_config = _load_user_config_module()
    settings_file = tmp_path / "config" / "settings.json"

    payload = user_config.save_settings(
        {
            "launch_at_login": True,
        },
        settings_file=settings_file,
    )

    expected = {
        "version": 1,
        "onboarding_completed": False,
        "launch_at_login": True,
        "display_language": "system",
        "theme": "dark",
        "background_mode": "balanced",
    }
    assert payload == expected
    assert json.loads(settings_file.read_text(encoding="utf-8")) == expected


def test_load_settings_repairs_invalid_display_language(tmp_path):
    user_config = _load_user_config_module()
    settings_file = tmp_path / "config" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(
        json.dumps(
            {
                "version": 1,
                "onboarding_completed": True,
                "launch_at_login": False,
                "display_language": "fr-FR",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = user_config.load_settings(settings_file=settings_file)

    expected = {
        "version": 1,
        "onboarding_completed": True,
        "launch_at_login": False,
        "display_language": "system",
        "theme": "dark",
        "background_mode": "balanced",
    }
    assert payload == expected
    assert json.loads(settings_file.read_text(encoding="utf-8")) == expected


def test_save_settings_accepts_theme_and_background_mode(tmp_path):
    user_config = _load_user_config_module()
    settings_file = tmp_path / "config" / "settings.json"

    payload = user_config.save_settings(
        {
            "theme": "light",
            "background_mode": "power_saver",
        },
        settings_file=settings_file,
    )

    assert payload["theme"] == "light"
    assert payload["background_mode"] == "power_saver"


def test_get_active_provider_config_returns_selected_complete_provider(tmp_path):
    user_config = _load_user_config_module()
    providers_file = tmp_path / "config" / "providers.json"
    providers_file.parent.mkdir(parents=True, exist_ok=True)
    providers_file.write_text(
        json.dumps(
            {
                "version": 1,
                "selected_provider": "cliproxyapi",
                "providers": {
                    "cliproxyapi": {
                        "api_key": "sk-demo",
                        "base_url": "https://example.invalid/v1",
                        "model": "gpt-5.4",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    provider = user_config.get_active_provider_config(providers_file=providers_file)

    assert provider == {
        "route": "cliproxyapi",
        "api_key": "sk-demo",
        "base_url": "https://example.invalid/v1",
        "model": "gpt-5.4",
    }

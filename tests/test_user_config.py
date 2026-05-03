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
        "theme_mode": "dark",
        "background_mode": "balanced",
        "action_plan_auto_generate": True,
        "voice_base_url": "",
        "voice_api_key": "",
        "voice_model": "FunAudioLLM/SenseVoiceSmall",
        "image_base_url": "",
        "image_api_key": "",
        "image_model": "",
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
        "version": 2,
        "selected_provider": None,
        "providers": {},
    }
    assert payload == expected
    assert json.loads(providers_file.read_text(encoding="utf-8")) == expected


def test_load_provider_config_normalizes_legacy_provider_to_v2(tmp_path):
    user_config = _load_user_config_module()
    providers_file = tmp_path / "config" / "providers.json"
    providers_file.parent.mkdir(parents=True, exist_ok=True)
    providers_file.write_text(
        json.dumps(
            {
                "version": 1,
                "selected_provider": "custom",
                "providers": {
                    "custom": {
                        "api_key": "sk-legacy",
                        "base_url": "http://127.0.0.1:8317/v1",
                        "model": "gpt-5.5",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = user_config.load_provider_config(providers_file=providers_file)

    assert payload == {
        "version": 2,
        "selected_provider": "custom",
        "providers": {
            "custom": {
                "route": "custom",
                "name": "custom",
                "type": "openai-compatible",
                "enabled": True,
                "api_key": "sk-legacy",
                "base_url": "http://127.0.0.1:8317/v1",
                "model": "gpt-5.5",
                "models": ["gpt-5.5"],
                "last_refreshed_at": None,
            }
        },
    }


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
        "theme_mode": "dark",
        "background_mode": "balanced",
        "action_plan_auto_generate": True,
        "voice_base_url": "",
        "voice_api_key": "",
        "voice_model": "FunAudioLLM/SenseVoiceSmall",
        "image_base_url": "",
        "image_api_key": "",
        "image_model": "",
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
        "theme_mode": "dark",
        "background_mode": "balanced",
        "action_plan_auto_generate": True,
        "voice_base_url": "",
        "voice_api_key": "",
        "voice_model": "FunAudioLLM/SenseVoiceSmall",
        "image_base_url": "",
        "image_api_key": "",
        "image_model": "",
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


def test_save_settings_accepts_auto_theme_and_voice_provider(tmp_path):
    user_config = _load_user_config_module()
    settings_file = tmp_path / "config" / "settings.json"

    payload = user_config.save_settings(
        {
            "theme": "light",
            "theme_mode": "auto",
            "voice_base_url": "https://voice.example.invalid/v1",
            "voice_api_key": "sk-voice",
            "voice_model": "FunAudioLLM/SenseVoiceSmall",
            "action_plan_auto_generate": False,
        },
        settings_file=settings_file,
    )

    assert payload["theme"] == "light"
    assert payload["theme_mode"] == "auto"
    assert payload["voice_base_url"] == "https://voice.example.invalid/v1"
    assert payload["voice_api_key"] == "sk-voice"
    assert payload["voice_model"] == "FunAudioLLM/SenseVoiceSmall"
    assert payload["action_plan_auto_generate"] is False


def test_get_voice_provider_config_requires_base_url_key_and_model(tmp_path):
    user_config = _load_user_config_module()
    settings_file = tmp_path / "config" / "settings.json"

    incomplete = user_config.get_voice_provider_config(settings_file=settings_file)
    assert incomplete["complete"] is False
    assert incomplete["missing"] == ["voice_base_url", "voice_api_key"]

    user_config.save_settings(
        {
            "voice_base_url": "https://voice.example.invalid/v1",
            "voice_api_key": "sk-voice",
            "voice_model": "sensevoice",
        },
        settings_file=settings_file,
    )

    complete = user_config.get_voice_provider_config(settings_file=settings_file)
    assert complete == {
        "base_url": "https://voice.example.invalid/v1",
        "api_key": "sk-voice",
        "model": "sensevoice",
        "complete": True,
        "missing": [],
    }


def test_get_image_provider_config_requires_base_url_key_and_model(tmp_path):
    user_config = _load_user_config_module()
    settings_file = tmp_path / "config" / "settings.json"

    incomplete = user_config.get_image_provider_config(settings_file=settings_file)
    assert incomplete["complete"] is False
    assert incomplete["missing"] == ["image_base_url", "image_api_key", "image_model"]

    user_config.save_settings(
        {
            "image_base_url": "https://images.example.invalid/v1",
            "image_api_key": "sk-image",
            "image_model": "image-model",
        },
        settings_file=settings_file,
    )

    complete = user_config.get_image_provider_config(settings_file=settings_file)
    assert complete == {
        "base_url": "https://images.example.invalid/v1",
        "api_key": "sk-image",
        "model": "image-model",
        "complete": True,
        "missing": [],
    }


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
        "name": "cliproxyapi",
        "type": "openai-compatible",
        "enabled": True,
        "api_key": "sk-demo",
        "base_url": "https://example.invalid/v1",
        "model": "gpt-5.4",
        "models": ["gpt-5.4"],
        "last_refreshed_at": None,
    }


def test_get_active_provider_config_falls_back_to_complete_provider_when_selected_is_empty(tmp_path):
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
                        "api_key": "",
                        "base_url": "",
                        "model": "",
                    },
                    "custom": {
                        "api_key": "sk-real",
                        "base_url": "http://127.0.0.1:8317/v1",
                        "model": "gpt-5.2",
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    provider = user_config.get_active_provider_config(providers_file=providers_file)

    assert provider == {
        "route": "custom",
        "name": "custom",
        "type": "openai-compatible",
        "enabled": True,
        "api_key": "sk-real",
        "base_url": "http://127.0.0.1:8317/v1",
        "model": "gpt-5.2",
        "models": ["gpt-5.2"],
        "last_refreshed_at": None,
    }


def test_get_active_provider_config_accepts_local_proxy_api_key_without_repo_env(tmp_path):
    user_config = _load_user_config_module()
    providers_file = tmp_path / "config" / "providers.json"
    providers_file.parent.mkdir(parents=True, exist_ok=True)
    providers_file.write_text(
        json.dumps(
            {
                "version": 2,
                "selected_provider": "custom",
                "providers": {
                    "custom": {
                        "api_key": "local-proxy-key",
                        "base_url": "",
                        "model": "",
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    provider = user_config.get_active_provider_config(providers_file=providers_file)

    assert provider == {
        "route": "custom",
        "name": "custom",
        "type": "openai-compatible",
        "enabled": True,
        "api_key": "local-proxy-key",
        "base_url": "http://127.0.0.1:8317/v1",
        "model": "",
        "models": [],
        "last_refreshed_at": None,
    }
    persisted = json.loads(providers_file.read_text(encoding="utf-8"))
    assert persisted["providers"]["custom"]["base_url"] == "http://127.0.0.1:8317/v1"


def test_get_provider_chain_config_orders_selected_and_skips_disabled(tmp_path):
    user_config = _load_user_config_module()
    providers_file = tmp_path / "config" / "providers.json"
    providers_file.parent.mkdir(parents=True, exist_ok=True)
    providers_file.write_text(
        json.dumps(
            {
                "version": 2,
                "selected_provider": "local",
                "providers": {
                    "disabled": {
                        "enabled": False,
                        "api_key": "sk-disabled",
                        "base_url": "https://disabled.invalid/v1",
                        "model": "gpt-disabled",
                    },
                    "cloud": {
                        "enabled": True,
                        "api_key": "sk-cloud",
                        "base_url": "https://cloud.invalid/v1",
                        "model": "gpt-5.4",
                        "models": ["gpt-5.4", "gpt-5.3"],
                    },
                    "local": {
                        "enabled": True,
                        "api_key": "sk-local",
                        "base_url": "http://127.0.0.1:8317/v1",
                        "model": "gpt-5.5",
                        "models": ["gpt-5.5"],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    chain = user_config.get_provider_chain_config(providers_file=providers_file)

    assert [provider["route"] for provider in chain] == ["local", "cloud"]
    assert chain[0]["models"] == ["gpt-5.5"]
    assert chain[1]["models"] == ["gpt-5.4", "gpt-5.3"]

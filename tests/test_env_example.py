import ast
from pathlib import Path
from unittest.mock import patch

from src.core.config import Config
from src.services.audio_service import AudioService


def _env_example_keys():
    keys = set()
    for line in Path(".env.example").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        keys.add(stripped.split("=", 1)[0])
    return keys


def _llm_client_env_fallback_keys():
    tree = ast.parse(Path("src/services/llm_client.py").read_text(encoding="utf-8"))
    keys = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "_provider_from_env":
            continue
        for keyword in node.keywords:
            if keyword.arg in {"base_url_key", "api_key_key", "model_key"} and isinstance(
                keyword.value,
                ast.Constant,
            ):
                keys.add(keyword.value.value)
    return keys


def test_env_example_documents_runtime_directory_keys_used_by_config():
    keys = _env_example_keys()
    with patch.object(
        Config,
        "get_runtime_paths",
        return_value={
            "app_mode": "development",
            "data_dir": Path("data"),
            "config_dir": Path("config"),
            "history_dir": Path("history"),
            "log_dir": Path("logs"),
            "plot_dir": Path("plot_outputs"),
            "cache_dir": Path("cache"),
            "runtime_dir": Path("runtime"),
            "migration_dir": Path("migration"),
        },
    ):
        runtime_keys = set(Config.build_runtime_environment())

    assert runtime_keys <= keys
    assert "VANTAGE_PLOT_OUTPUT_DIR" not in keys


def test_env_example_documents_media_root_migration_keys():
    keys = _env_example_keys()

    assert "VANTAGE_LEGACY_MEDIA_ROOT" in keys
    assert "VANTAGE_PHOTO_ROOTS" in keys


def test_env_example_documents_explicit_fail_closed_location_override():
    text = Path(".env.example").read_text(encoding="utf-8")

    assert "user-declared fixed location override" in text
    assert "location remains unavailable and no city is guessed" in text
    assert "VANTAGE_STATIC_LATITUDE=" in text
    assert "VANTAGE_STATIC_LONGITUDE=" in text


def test_env_example_documents_llm_env_fallback_keys_used_by_llm_client():
    keys = _env_example_keys()
    expected = _llm_client_env_fallback_keys()

    assert expected <= keys


def test_env_example_documents_transcription_env_fallback_keys():
    keys = _env_example_keys()

    assert {
        "VANTAGE_TRANSCRIBE_BASE_URL",
        "VANTAGE_TRANSCRIBE_API_KEY",
        "VANTAGE_TRANSCRIBE_MODEL",
    } <= keys


def test_audio_service_uses_documented_transcription_env_keys(monkeypatch):
    for key in (
        "VANTAGE_TRANSCRIBE_BASE_URL",
        "VANTAGE_TRANSCRIBE_API_KEY",
        "VANTAGE_TRANSCRIBE_MODEL",
        "SILICONFLOW_BASE_URL",
        "SILICONFLOW_API_KEY",
        "SILICONFLOW_AUDIO_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VANTAGE_TRANSCRIBE_BASE_URL", "https://voice.example.invalid/v1")
    monkeypatch.setenv("VANTAGE_TRANSCRIBE_API_KEY", "sk-voice")
    monkeypatch.setenv("VANTAGE_TRANSCRIBE_MODEL", "sensevoice")

    config = AudioService._resolve_transcription_config()

    assert config == {
        "base_url": "https://voice.example.invalid/v1",
        "api_key": "sk-voice",
        "model": "sensevoice",
    }


def test_audio_service_keeps_legacy_siliconflow_transcription_env_fallback(monkeypatch):
    for key in (
        "VANTAGE_TRANSCRIBE_BASE_URL",
        "VANTAGE_TRANSCRIBE_API_KEY",
        "VANTAGE_TRANSCRIBE_MODEL",
        "SILICONFLOW_BASE_URL",
        "SILICONFLOW_API_KEY",
        "SILICONFLOW_AUDIO_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SILICONFLOW_BASE_URL", "https://legacy.example.invalid/v1")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-legacy")
    monkeypatch.setenv("SILICONFLOW_AUDIO_MODEL", "legacy-sensevoice")

    config = AudioService._resolve_transcription_config()

    assert config == {
        "base_url": "https://legacy.example.invalid/v1",
        "api_key": "sk-legacy",
        "model": "legacy-sensevoice",
    }


def test_audio_service_prefers_explicit_transcription_args_over_env(monkeypatch):
    monkeypatch.setenv("VANTAGE_TRANSCRIBE_BASE_URL", "https://voice.example.invalid/v1")
    monkeypatch.setenv("VANTAGE_TRANSCRIBE_API_KEY", "sk-voice")
    monkeypatch.setenv("VANTAGE_TRANSCRIBE_MODEL", "sensevoice")

    config = AudioService._resolve_transcription_config(
        base_url="https://explicit.example.invalid/v1",
        api_key="sk-explicit",
        model="explicit-model",
    )

    assert config == {
        "base_url": "https://explicit.example.invalid/v1",
        "api_key": "sk-explicit",
        "model": "explicit-model",
    }

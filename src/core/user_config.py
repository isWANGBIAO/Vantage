import json
from copy import deepcopy
from pathlib import Path

from src.core.config import Config

SETTINGS_FILE_NAME = "settings.json"
PROVIDERS_FILE_NAME = "providers.json"
MIGRATION_STATE_FILE_NAME = "migration-state.json"

SETTINGS_VERSION = 1
PROVIDERS_VERSION = 1
MIGRATION_STATE_VERSION = 1

DEFAULT_SETTINGS = {
    "version": SETTINGS_VERSION,
    "onboarding_completed": False,
    "launch_at_login": False,
    "display_language": "system",
    "theme": "dark",
    "background_mode": "balanced",
}

DEFAULT_PROVIDER_CONFIG = {
    "version": PROVIDERS_VERSION,
    "selected_provider": None,
    "providers": {},
}

DEFAULT_MIGRATION_STATE = {
    "version": MIGRATION_STATE_VERSION,
    "completed": False,
    "source_path": None,
    "imported_at": None,
}


def get_settings_file(config_dir: str | Path | None = None) -> Path:
    resolved_config_dir = Path(config_dir) if config_dir else Path(Config.get_config_dir())
    resolved_config_dir.mkdir(parents=True, exist_ok=True)
    return resolved_config_dir / SETTINGS_FILE_NAME


def get_providers_file(config_dir: str | Path | None = None) -> Path:
    resolved_config_dir = Path(config_dir) if config_dir else Path(Config.get_config_dir())
    resolved_config_dir.mkdir(parents=True, exist_ok=True)
    return resolved_config_dir / PROVIDERS_FILE_NAME


def get_migration_state_file(migration_dir: str | Path | None = None) -> Path:
    resolved_migration_dir = Path(migration_dir) if migration_dir else Path(Config.get_migration_dir())
    resolved_migration_dir.mkdir(parents=True, exist_ok=True)
    return resolved_migration_dir / MIGRATION_STATE_FILE_NAME


def build_default_settings() -> dict:
    return deepcopy(DEFAULT_SETTINGS)


def build_default_provider_config() -> dict:
    return deepcopy(DEFAULT_PROVIDER_CONFIG)


def build_default_migration_state() -> dict:
    return deepcopy(DEFAULT_MIGRATION_STATE)


def _read_json_payload(target_file: str | Path) -> dict | None:
    resolved_file = Path(target_file)
    if not resolved_file.exists():
        return None

    try:
        payload = json.loads(resolved_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None

    return payload if isinstance(payload, dict) else None


def _write_json_payload(target_file: str | Path, payload: dict) -> dict:
    resolved_file = Path(target_file)
    resolved_file.parent.mkdir(parents=True, exist_ok=True)
    resolved_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _coerce_bool(payload: dict | None, key: str, default: bool) -> bool:
    value = payload.get(key) if isinstance(payload, dict) else default
    return value if isinstance(value, bool) else default


def _coerce_optional_str(payload: dict | None, key: str) -> str | None:
    value = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    return normalized or None


def _coerce_dict(payload: dict | None, key: str) -> dict:
    value = payload.get(key) if isinstance(payload, dict) else None
    return deepcopy(value) if isinstance(value, dict) else {}


def _coerce_display_language(payload: dict | None, key: str = "display_language") -> str:
    value = payload.get(key) if isinstance(payload, dict) else None
    if value in {"system", "zh-CN", "en-US"}:
        return value
    return "system"


def _coerce_theme(payload: dict | None, key: str = "theme") -> str:
    value = payload.get(key) if isinstance(payload, dict) else None
    if value in {"dark", "light"}:
        return value
    return "dark"


def _coerce_background_mode(payload: dict | None, key: str = "background_mode") -> str:
    value = payload.get(key) if isinstance(payload, dict) else None
    if value in {"balanced", "prewarm", "power_saver"}:
        return value
    return "balanced"


def _sanitize_provider_entry(entry: dict | None) -> dict:
    return {
        "api_key": _coerce_optional_str(entry, "api_key") or "",
        "base_url": _coerce_optional_str(entry, "base_url") or "",
        "model": _coerce_optional_str(entry, "model") or "",
    }


def _sanitize_settings(payload: dict | None) -> dict:
    return {
        "version": SETTINGS_VERSION,
        "onboarding_completed": _coerce_bool(payload, "onboarding_completed", False),
        "launch_at_login": _coerce_bool(payload, "launch_at_login", False),
        "display_language": _coerce_display_language(payload),
        "theme": _coerce_theme(payload),
        "background_mode": _coerce_background_mode(payload),
    }


def _sanitize_provider_config(payload: dict | None) -> dict:
    providers = {}
    raw_providers = _coerce_dict(payload, "providers")
    for key, entry in raw_providers.items():
        normalized_key = str(key).strip() if isinstance(key, str) else ""
        if not normalized_key:
            continue
        providers[normalized_key] = _sanitize_provider_entry(entry if isinstance(entry, dict) else None)

    return {
        "version": PROVIDERS_VERSION,
        "selected_provider": _coerce_optional_str(payload, "selected_provider"),
        "providers": providers,
    }


def _sanitize_migration_state(payload: dict | None) -> dict:
    return {
        "version": MIGRATION_STATE_VERSION,
        "completed": _coerce_bool(payload, "completed", False),
        "source_path": _coerce_optional_str(payload, "source_path"),
        "imported_at": _coerce_optional_str(payload, "imported_at"),
    }


def _load_sanitized_payload(target_file: str | Path, sanitizer) -> dict:
    payload = _read_json_payload(target_file)
    sanitized = sanitizer(payload)
    if payload != sanitized:
        return _write_json_payload(target_file, sanitized)
    return sanitized


def load_settings(settings_file: str | Path | None = None) -> dict:
    resolved_settings_file = Path(settings_file) if settings_file else get_settings_file()
    return _load_sanitized_payload(resolved_settings_file, _sanitize_settings)


def save_settings(payload: dict | None, settings_file: str | Path | None = None) -> dict:
    resolved_settings_file = Path(settings_file) if settings_file else get_settings_file()
    return _write_json_payload(resolved_settings_file, _sanitize_settings(payload))


def load_provider_config(providers_file: str | Path | None = None) -> dict:
    resolved_providers_file = Path(providers_file) if providers_file else get_providers_file()
    return _load_sanitized_payload(resolved_providers_file, _sanitize_provider_config)


def save_provider_config(payload: dict | None, providers_file: str | Path | None = None) -> dict:
    resolved_providers_file = Path(providers_file) if providers_file else get_providers_file()
    return _write_json_payload(resolved_providers_file, _sanitize_provider_config(payload))


def get_active_provider_config(providers_file: str | Path | None = None) -> dict | None:
    provider_config = load_provider_config(providers_file=providers_file)
    route = _coerce_optional_str(provider_config, "selected_provider")
    if not route:
        return None

    providers = provider_config.get("providers")
    if not isinstance(providers, dict):
        return None

    provider = providers.get(route)
    if not isinstance(provider, dict):
        return None

    api_key = _coerce_optional_str(provider, "api_key")
    base_url = _coerce_optional_str(provider, "base_url")
    model = _coerce_optional_str(provider, "model")
    if not api_key or not base_url or not model:
        return None

    return {
        "route": route,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    }


def load_migration_state(migration_state_file: str | Path | None = None) -> dict:
    resolved_migration_state_file = (
        Path(migration_state_file) if migration_state_file else get_migration_state_file()
    )
    return _load_sanitized_payload(resolved_migration_state_file, _sanitize_migration_state)


def save_migration_state(payload: dict | None, migration_state_file: str | Path | None = None) -> dict:
    resolved_migration_state_file = (
        Path(migration_state_file) if migration_state_file else get_migration_state_file()
    )
    return _write_json_payload(resolved_migration_state_file, _sanitize_migration_state(payload))

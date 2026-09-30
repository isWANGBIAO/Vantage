"""Validated settings persistence and onboarding HTTP routes."""

import logging
import os
import shutil
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.core.config import Config
from src.core.provider_credentials import _destination_bound_api_key, _provider_destination
from src.core.user_config import (
    MAX_ACTION_PLAN_CHECK_INTERVAL_MINUTES,
    USER_CONFIG_LOCK,
    _atomic_write_bytes,
    _sanitize_provider_config,
    _sanitize_settings,
    get_migration_state_file,
    get_provider_chain_config,
    get_providers_file,
    get_settings_file,
    load_migration_state,
    load_provider_config,
    load_settings,
    save_migration_state,
    save_provider_config,
    save_settings,
)

from .api_contracts import (
    SettingsState, DisplayLanguageState, OnboardingState, OnboardingCompletion, ConfigurationErrorResponse,
)
from src.services.automation_catalog import get_operation


def _request_contract(name):
    return {"requestBody": {"required": True, "content": {
        "application/json": {"schema": get_operation(name).input_schema},
    }}}


router = APIRouter(responses={503: {"model": ConfigurationErrorResponse}})

_automation_config_lock = USER_CONFIG_LOCK

_AUTOMATION_SETTINGS_FIELDS = frozenset({
    "display_language",
    "theme",
    "theme_mode",
    "launch_at_login",
    "action_plan_auto_generate",
    "action_plan_check_interval_minutes",
    "voice_provider_mode",
    "voice_base_url",
    "voice_api_key",
    "voice_model",
    "voice_models",
    "voice_last_refreshed_at",
    "image_provider_mode",
    "image_base_url",
    "image_api_key",
    "image_model",
    "image_models",
    "image_last_refreshed_at",
})

def _validate_automation_payload(payload, allowed_fields):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Request body must be an object.")
    unknown = set(payload) - allowed_fields
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported settings field: {next(iter(unknown))}",
        )
    return payload

def _validate_provider_configuration_payload(payload):
    if "provider_config" in payload:
        submitted = payload["provider_config"]
        if not isinstance(submitted, dict):
            raise HTTPException(status_code=422, detail="provider_config must be an object.")
        if "providers" in submitted:
            providers = submitted["providers"]
            if not isinstance(providers, dict):
                raise HTTPException(status_code=422, detail="provider_config.providers must be an object.")
            if any(not isinstance(entry, dict) for entry in providers.values()):
                raise HTTPException(
                    status_code=422,
                    detail="provider_config.providers entries must be objects.",
                )
        return


def _masked_settings_payload():
    settings = load_settings()
    settings_payload = dict(settings)
    for key in ("voice_api_key", "image_api_key"):
        has_key = bool(str(settings.get(key) or "").strip())
        settings_payload[key] = "********" if has_key else ""
        settings_payload[f"{key.removesuffix('_api_key')}_has_api_key"] = has_key

    provider = load_provider_config()
    masked_providers = {}
    for route, entry in provider.get("providers", {}).items():
        masked_entry = {
            key: entry[key]
            for key in (
                "route",
                "name",
                "type",
                "enabled",
                "api_key",
                "base_url",
                "model",
                "models",
                "last_refreshed_at",
                "context_window_tokens",
                "max_output_tokens",
            )
            if key in entry
        }
        has_key = bool(str(entry.get("api_key") or "").strip())
        masked_entry["api_key"] = "********" if has_key else ""
        masked_providers[route] = masked_entry
    provider_payload = {**provider, "providers": masked_providers}
    migration = load_migration_state()
    runtime_paths = Config.get_runtime_paths()
    return {
        "settings": settings_payload,
        "provider": provider_payload,
        "migration": {
            "completed": migration["completed"],
            "source_path": migration["source_path"],
            "imported_at": migration["imported_at"],
        },
        "runtime_paths": {key: str(value) for key, value in runtime_paths.items()},
    }

def _configuration_api_key(submitted_key, base_url, saved_key, saved_base_url):
    # Saving must not silently discard a user's only copy of a write-only key.
    # A literal empty key is an explicit clear; omission/masking means preserve.
    submitted_key = None if submitted_key is None else str(submitted_key).strip()
    if submitted_key == "":
        return ""
    destination = _provider_destination(base_url)
    if (saved_key and submitted_key in (None, "********")
            and (destination is None or destination != _provider_destination(saved_base_url))):
        raise HTTPException(
            status_code=422,
            detail="Changing a provider destination requires an explicit API key, or an explicit empty key to clear the saved credential.",
        )
    return _destination_bound_api_key(submitted_key, base_url, saved_key, saved_base_url)


def _prepare_provider_configuration(payload, current_provider):
    if "provider_config" in payload:
        submitted = dict(payload["provider_config"])
        for key in ("selected_provider", "sampling_defaults", "model_profiles"):
            submitted.setdefault(key, current_provider.get(key))
        if "providers" in submitted:
            submitted_providers = submitted["providers"]
        else:
            submitted_providers = current_provider.get("providers", {})

        merged_providers = {}
        for route, submitted_entry in submitted_providers.items():
            old_entry = current_provider.get("providers", {}).get(route, {})
            entry = {**old_entry, **submitted_entry}
            entry["api_key"] = _configuration_api_key(
                submitted_entry.get("api_key"), entry.get("base_url", ""),
                old_entry.get("api_key", ""), old_entry.get("base_url", ""),
            )
            merged_providers[route] = entry
        submitted["providers"] = merged_providers
        return submitted

    return None

def _snapshot_config_file(path):
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None

def _snapshot_automation_config_files():
    return {
        path: _snapshot_config_file(path)
        for path in (get_settings_file(), get_providers_file())
    }

def _restore_config_files(original_files, update_error):
    rollback_errors = []
    for path, original_contents in reversed(list(original_files.items())):
        try:
            if original_contents is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write_bytes(path, original_contents)
        except Exception as rollback_error:
            rollback_errors.append((path, rollback_error))
    if rollback_errors:
        for path, rollback_error in rollback_errors:
            logging.error(
                "Failed to restore settings file %s after a failed settings update: %s",
                path,
                rollback_error,
            )
        raise RuntimeError("Settings update failed and one or more files could not be restored.") from update_error

def _persist_automation_settings_update(settings_payload, provider_payload):
    writes = []
    if settings_payload is not None:
        writes.append((get_settings_file(), save_settings, settings_payload))
    if provider_payload is not None:
        writes.append((get_providers_file(), save_provider_config, provider_payload))
    if not writes:
        return

    for _, save_payload, payload in writes:
        save_payload(payload)

@router.get("/api/v1/settings", response_model=SettingsState, response_model_exclude_unset=True)
def get_automation_settings():
    with _automation_config_lock:
        return _masked_settings_payload()

@router.put("/api/v1/settings", response_model=SettingsState, response_model_exclude_unset=True,
            openapi_extra=_request_contract("settings.update"))
def update_automation_settings(payload: dict):
    with _automation_config_lock:
        _validate_automation_payload(payload, _AUTOMATION_SETTINGS_FIELDS | {"provider_config"})
        interval = payload.get("action_plan_check_interval_minutes")
        if "action_plan_check_interval_minutes" in payload and (
            not isinstance(interval, int)
            or isinstance(interval, bool)
            or interval < 0
            or interval > MAX_ACTION_PLAN_CHECK_INTERVAL_MINUTES
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "action_plan_check_interval_minutes must be an integer from 0 to "
                    f"{MAX_ACTION_PLAN_CHECK_INTERVAL_MINUTES}."
                ),
            )
        _validate_provider_configuration_payload(payload)
        original_files = _snapshot_automation_config_files()
        try:
            settings_updates = {key: value for key, value in payload.items() if key in _AUTOMATION_SETTINGS_FIELDS}
            current_settings = load_settings()
            for prefix in ("voice", "image"):
                key, base = f"{prefix}_api_key", f"{prefix}_base_url"
                if key in payload or base in payload:
                    settings_updates[key] = _configuration_api_key(
                        payload.get(key), payload.get(base, current_settings.get(base, "")),
                        current_settings.get(key, ""), current_settings.get(base, ""),
                    )
            current_provider = load_provider_config()
            settings_to_save = _sanitize_settings({**current_settings, **settings_updates}) if settings_updates else None
            provider_to_save = _prepare_provider_configuration(payload, current_provider)
            if provider_to_save is not None:
                provider_to_save = _sanitize_provider_config(provider_to_save)

            _persist_automation_settings_update(settings_to_save, provider_to_save)
            return _masked_settings_payload()
        except Exception as update_error:
            _restore_config_files(original_files, update_error)
            raise

@router.get("/api/v1/settings/display-language", response_model=DisplayLanguageState, response_model_exclude_unset=True)
def get_automation_display_language():
    with _automation_config_lock:
        return {"display_language": load_settings().get("display_language", "system")}

@router.put("/api/v1/settings/display-language", response_model=DisplayLanguageState, response_model_exclude_unset=True,
            openapi_extra=_request_contract("settings.display_language.update"))
def update_automation_display_language(payload: dict):
    _validate_automation_payload(payload, {"display_language"})
    if "display_language" not in payload:
        raise HTTPException(status_code=422, detail="display_language is required.")
    with _automation_config_lock:
        settings = load_settings()
        saved = save_settings({**settings, "display_language": payload["display_language"]})
        return {"display_language": saved["display_language"]}

def _detect_automation_legacy_root():
    project_root = Path(Config.get_project_root()).expanduser().resolve()
    data_dir = Path(Config.get_data_dir()).expanduser().resolve()
    if project_root == data_dir or data_dir in project_root.parents:
        return None
    return str(project_root) if (project_root / "history").is_dir() else None

@router.get("/api/v1/onboarding", response_model=OnboardingState, response_model_exclude_unset=True)
def get_automation_onboarding_state():
    with _automation_config_lock:
        settings = load_settings()
        provider_configured = bool(get_provider_chain_config())
        migration = load_migration_state()
        return {
            "completed": settings["onboarding_completed"],
            "launchAtLogin": settings["launch_at_login"],
            "displayLanguage": settings["display_language"],
            "providerConfigured": provider_configured,
            "migrationCompleted": migration["completed"],
            "legacyRoot": migration["source_path"] or _detect_automation_legacy_root(),
        }

def _validate_legacy_history_source(legacy_root):
    if not isinstance(legacy_root, str) or not legacy_root.strip():
        raise HTTPException(status_code=400, detail="Legacy history import requires a source folder.")
    source_root_input = Path(legacy_root).expanduser()
    if not source_root_input.is_absolute():
        raise HTTPException(status_code=400, detail="Legacy history source must be an absolute path.")
    try:
        if source_root_input.is_symlink():
            raise HTTPException(status_code=400, detail="Legacy history source cannot be a symbolic link.")
        source_root = source_root_input.resolve(strict=True)
    except OSError:
        raise HTTPException(status_code=400, detail="Legacy history source folder was not found.") from None
    if not source_root.is_dir():
        raise HTTPException(status_code=400, detail="Legacy history source must be a folder.")

    source_history = source_root / "history"
    if source_history.is_symlink() or not source_history.is_dir():
        raise HTTPException(status_code=400, detail="Legacy history folder was not found in the selected source.")
    target_history_input = Path(Config.get_history_dir()).expanduser()
    if target_history_input.is_symlink():
        raise HTTPException(status_code=400, detail="Configured history destination cannot be a symbolic link.")
    target_history = target_history_input.resolve()
    source_history = source_history.resolve()
    if source_history == target_history:
        return source_root, source_history, target_history, True
    if source_root == target_history or target_history.is_relative_to(source_history) or source_root.is_relative_to(target_history):
        raise HTTPException(status_code=400, detail="Legacy history source overlaps the configured destination.")
    return source_root, source_history, target_history, False

def _copy_missing_legacy_history(source_history: Path, target_history: Path):
    target_history.mkdir(parents=True, exist_ok=True)
    target_root = target_history.resolve()
    for current_dir, dir_names, file_names in os.walk(source_history, followlinks=False):
        current_path = Path(current_dir)
        relative_dir = current_path.relative_to(source_history)
        destination_dir = target_history / relative_dir
        if destination_dir.is_symlink() or not destination_dir.resolve().is_relative_to(target_root):
            raise HTTPException(status_code=400, detail="Legacy history destination escapes the configured history directory.")
        destination_dir.mkdir(parents=True, exist_ok=True)
        dir_names[:] = [name for name in dir_names if not (current_path / name).is_symlink()]
        for name in file_names:
            source_file = current_path / name
            if source_file.is_symlink() or not source_file.is_file():
                continue
            destination_file = destination_dir / name
            if destination_file.is_symlink() or not destination_file.resolve().is_relative_to(target_root):
                raise HTTPException(status_code=400, detail="Legacy history destination escapes the configured history directory.")
            if destination_file.exists():
                continue
            try:
                with source_file.open("rb") as source, destination_file.open("xb") as destination:
                    shutil.copyfileobj(source, destination)
            except FileExistsError:
                continue
            except OSError as error:
                with suppress(OSError):
                    destination_file.unlink()
                raise HTTPException(status_code=500, detail="Failed to copy a legacy history file.") from error

@router.post("/api/v1/onboarding/complete", response_model=OnboardingCompletion,
             openapi_extra=_request_contract("onboarding.complete"))
def complete_automation_onboarding(payload: dict):
    with _automation_config_lock:
        originals = _snapshot_automation_config_files()
        originals[get_migration_state_file()] = _snapshot_config_file(get_migration_state_file())
        try:
            return _complete_onboarding(payload)
        except Exception as error:
            _restore_config_files(originals, error)
            raise


def _complete_onboarding(payload: dict):
    allowed_fields = {
        "display_language",
        "launch_at_login",
        "selected_provider",
        "base_url",
        "api_key",
        "model",
        "skip_chat_setup",
        "import_legacy_data",
        "legacy_root",
    }
    _validate_automation_payload(payload, allowed_fields)
    if not isinstance(payload.get("skip_chat_setup"), bool):
        raise HTTPException(status_code=422, detail="skip_chat_setup must be an explicit boolean choice.")
    if "launch_at_login" in payload and not isinstance(payload["launch_at_login"], bool):
        raise HTTPException(status_code=422, detail="launch_at_login must be a boolean.")
    if payload["skip_chat_setup"] is False:
        selected_provider = payload.get("selected_provider")
        if not isinstance(selected_provider, str) or not selected_provider.strip():
            raise HTTPException(
                status_code=422,
                detail="selected_provider is required when skip_chat_setup is false.",
            )
    should_import = payload.get("import_legacy_data") is True
    validated_source = None
    if should_import:
        validated_source = _validate_legacy_history_source(payload.get("legacy_root"))

    with _automation_config_lock:
        existing_migration = load_migration_state()
    migration = {
        "imported": False,
        "completed": existing_migration["completed"],
        "sourcePath": existing_migration["source_path"],
    }

    if should_import and validated_source:
        source_root, source_history, target_history, same_root = validated_source
        if not same_root and not (existing_migration["completed"] and existing_migration["source_path"] == str(source_root)):
            _copy_missing_legacy_history(source_history, target_history)
            imported = True
        else:
            imported = False

    with _automation_config_lock:
        saved_provider = load_provider_config()
        if payload["skip_chat_setup"] is False:
            selected_provider = payload["selected_provider"].strip()
            providers = dict(saved_provider.get("providers", {}))
            old_entry = dict(providers.get(selected_provider, {}))
            submitted_model = str(payload.get("model") or "").strip()
            old_model = old_entry.get("model", "")
            model = submitted_model or old_model
            submitted_api_key = str(payload.get("api_key") or "").strip()
            if submitted_api_key == "********":
                submitted_api_key = ""
            old_base_url = old_entry.get("base_url", "")
            submitted_base_url = str(payload.get("base_url") or "").strip()
            base_url = submitted_base_url or old_base_url
            model_changed = bool(submitted_model and submitted_model != old_model)
            base_url_changed = bool(submitted_base_url and submitted_base_url != old_base_url)
            old_models = old_entry.get("models", [])
            providers[selected_provider] = {
                **old_entry,
                "route": selected_provider,
                "name": old_entry.get("name") or selected_provider,
                "type": old_entry.get("type") or "openai-compatible",
                "enabled": True,
                "api_key": _configuration_api_key(
                    submitted_api_key or None, base_url, old_entry.get("api_key", ""), old_base_url,
                ),
                "base_url": base_url,
                "model": model,
                "models": [model] if model_changed else old_models,
                "last_refreshed_at": None if model_changed or base_url_changed else old_entry.get("last_refreshed_at"),
            }
            provider_config = {
                **saved_provider,
                "selected_provider": selected_provider,
                "providers": providers,
            }

        if should_import and validated_source:
            source_root = validated_source[0]
            migration_state = load_migration_state()
            imported_at = migration_state["imported_at"] or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            saved_migration = save_migration_state({
                "completed": True,
                "source_path": str(source_root),
                "imported_at": imported_at,
            })
            migration = {
                "imported": imported,
                "completed": saved_migration["completed"],
                "sourcePath": saved_migration["source_path"],
            }

        if payload["skip_chat_setup"] is False:
            saved_provider = save_provider_config(provider_config)
        provider_configured = bool(get_provider_chain_config())
        if payload["skip_chat_setup"] is False and not provider_configured:
            raise HTTPException(status_code=422, detail="Complete provider credentials are required unless chat setup is skipped.")
        current_settings = load_settings()
        saved_settings = save_settings({
            **current_settings,
            "onboarding_completed": True,
            "launch_at_login": payload.get("launch_at_login", current_settings["launch_at_login"]),
            "display_language": payload.get("display_language", current_settings["display_language"]),
        })
        return {
            "completed": True,
            "launchAtLogin": saved_settings["launch_at_login"],
            "providerConfigured": provider_configured,
            "migration": migration,
            "settings": {
                "display_language": saved_settings["display_language"],
                "theme": saved_settings["theme"],
                "theme_mode": saved_settings["theme_mode"],
                "launch_at_login": saved_settings["launch_at_login"],
            },
            "provider": {
                "selected_provider": saved_provider["selected_provider"],
                "providers": list(saved_provider["providers"]),
            },
        }

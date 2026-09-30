"""Provider configuration resolution, readiness checks, and model discovery."""

import asyncio
import time
from typing import Optional

import requests
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.core.provider_credentials import _destination_bound_api_key
from src.core.user_config import (
    DEFAULT_LOCAL_PROXY_BASE_URL,
    LOCAL_PROXY_PROVIDER_ROUTES,
    get_provider_chain_config,
    load_provider_config,
    load_settings,
)
from src.services.llm_client import LLMClient
from src.utils.sensitive_data import redact_sensitive_text

from . import chat as _chat
from . import settings as _settings

router = APIRouter()

ACTION_PLAN_PROVIDER_READY_TIMEOUT_SECONDS = 300

ACTION_PLAN_PROVIDER_READY_POLL_SECONDS = 2.0

ACTION_PLAN_PROVIDER_READY_REQUEST_TIMEOUT_SECONDS = 3

def _is_local_provider_base_url(base_url: str | None) -> bool:
    normalized = str(base_url or "").strip().lower()
    return (
        "://127.0.0.1" in normalized
        or "://localhost" in normalized
        or "://[::1]" in normalized
    )

def _resolve_action_plan_ready_provider(provider_route: str | None = None) -> dict | None:
    providers = get_provider_chain_config()
    if not providers:
        return None

    normalized_route = str(provider_route or "").strip()
    if normalized_route:
        for provider in providers:
            if provider.get("route") == normalized_route:
                return provider

    return providers[0]

def _probe_provider_models_endpoint(provider: dict) -> dict:
    base_url = str(provider.get("base_url") or "").rstrip("/")
    api_key = str(provider.get("api_key") or "").strip()
    if not base_url:
        return {"ready": False, "error": "provider base URL is empty"}

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{base_url}/models"
    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=ACTION_PLAN_PROVIDER_READY_REQUEST_TIMEOUT_SECONDS,
        )
        return {
            "ready": True,
            "status_code": response.status_code,
            "url": url,
        }
    except requests.RequestException as exc:
        return {
            "ready": False,
            "error": str(exc),
            "url": url,
        }

async def _wait_for_action_plan_provider_ready(provider_route: str | None = None) -> dict:
    provider = _resolve_action_plan_ready_provider(provider_route)
    if not provider:
        return {
            "ready": False,
            "route": str(provider_route or "").strip(),
            "base_url": "",
            "error": "No configured AI provider is available.",
        }

    base_url = str(provider.get("base_url") or "").rstrip("/")
    route = provider.get("route") or provider_route or ""
    if not _is_local_provider_base_url(base_url):
        return {
            "ready": True,
            "route": route,
            "base_url": base_url,
            "skipped": True,
        }

    deadline = time.monotonic() + ACTION_PLAN_PROVIDER_READY_TIMEOUT_SECONDS
    last_probe = {
        "ready": False,
        "error": "provider readiness was not checked",
    }
    while True:
        last_probe = await asyncio.to_thread(_probe_provider_models_endpoint, provider)
        if last_probe.get("ready"):
            return {
                **last_probe,
                "route": route,
                "base_url": base_url,
            }

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {
                **last_probe,
                "route": route,
                "base_url": base_url,
            }

        await asyncio.sleep(min(ACTION_PLAN_PROVIDER_READY_POLL_SECONDS, remaining))

class LLMModelDiscoverRequest(BaseModel):
    route: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    type: Optional[str] = None

class ProviderModelDiscoverRequest(BaseModel):
    kind: Optional[str] = None
    mode: Optional[str] = None
    route: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    type: Optional[str] = None

@router.get("/api/v1/models")
async def list_llm_models():
    return await asyncio.to_thread(_build_llm_models_payload)


def _build_llm_models_payload():
    try:
        client = LLMClient()
    except Exception as error:
        return {"models": [], "providers": [], "default_model": None, "error": str(error)}

    providers = client.get_model_catalog()
    seen = set()
    models = []
    model_options = []
    for provider in providers:
        provider_route = provider.get("route")
        provider_label = provider.get("name") or provider_route
        for model in provider.get("models", []):
            if model and model not in seen:
                seen.add(model)
                models.append(model)
            if model and provider_route:
                model_profile = client._model_parameter_profile(model)
                model_aliases = (
                    model_profile.get("reasoning_aliases")
                    if isinstance(model_profile, dict)
                    else None
                )
                model_options.append({
                    "id": f"{provider_route}::{model}",
                    "model": model,
                    "provider_route": provider_route,
                    "provider_label": provider_label,
                    "label": f"{model} | {provider_label}",
                    "reasoning_tiers": client._reasoning_tiers_for_model(model),
                    "reasoning_aliases": (
                        dict(model_aliases) if isinstance(model_aliases, dict) else {}
                    ),
                    "default_reasoning_effort": client._normalize_reasoning_effort_for_model(
                        provider,
                        model,
                        _chat.DEFAULT_CHAT_REASONING_EFFORT,
                    ),
                    "is_default": (
                        provider is providers[0]
                        and model == provider.get("model")
                    ),
                })

    return {
        "models": models,
        "providers": providers,
        "default_model": providers[0]["model"] if providers else None,
        "default_provider_route": providers[0]["route"] if providers else None,
        "model_options": model_options,
    }

def _resolve_discover_secret(request: LLMModelDiscoverRequest):
    route = (request.route or "").strip()
    api_key = (request.api_key or "").strip()
    base_url = (request.base_url or "").strip()
    provider_type = (request.type or "openai-compatible").strip()

    if (not api_key or api_key == "********" or not base_url) and route:
        saved_config = load_provider_config()
        saved_provider = saved_config.get("providers", {}).get(route)
        if isinstance(saved_provider, dict):
            saved_base_url = str(saved_provider.get("base_url") or "").strip()
            if not saved_base_url and route.lower() in LOCAL_PROXY_PROVIDER_ROUTES:
                saved_base_url = DEFAULT_LOCAL_PROXY_BASE_URL
            if not base_url:
                base_url = saved_base_url
            api_key = _destination_bound_api_key(
                api_key, base_url, saved_provider.get("api_key"), saved_base_url,
            )
            provider_type = str(saved_provider.get("type") or provider_type).strip()

    if not base_url and route.lower() in LOCAL_PROXY_PROVIDER_ROUTES:
        base_url = DEFAULT_LOCAL_PROXY_BASE_URL

    return {
        "route": route or "custom",
        "base_url": base_url,
        "api_key": api_key,
        "type": provider_type or "openai-compatible",
    }

def _redact_api_key_from_message(message: str, api_key: str | None = None) -> str:
    redacted = str(message or "")
    if api_key:
        redacted = redacted.replace(api_key, "[REDACTED_API_KEY]")
    return redact_sensitive_text(redacted)

def _normalize_special_provider_kind(kind: str | None) -> str:
    normalized = str(kind or "").strip().lower()
    return normalized if normalized in {"voice", "image"} else "voice"

def _normalize_special_provider_mode(mode: str | None, settings: dict, kind: str) -> str:
    normalized = str(mode or settings.get(f"{kind}_provider_mode") or "").strip()
    if normalized == "custom":
        return "custom"
    if normalized == "inherit_ai":
        return "inherit_ai"
    if settings.get(f"{kind}_base_url") or settings.get(f"{kind}_api_key"):
        return "custom"
    return "inherit_ai"

def _first_complete_ai_provider():
    provider_config = load_provider_config()
    providers = provider_config.get("providers") if isinstance(provider_config, dict) else {}
    if not isinstance(providers, dict):
        return None

    candidate_routes = []
    selected = str(provider_config.get("selected_provider") or "").strip()
    if selected:
        candidate_routes.append(selected)
    candidate_routes.extend(route for route in providers if route not in candidate_routes)

    for route in candidate_routes:
        provider = providers.get(route)
        if not isinstance(provider, dict) or provider.get("enabled") is False:
            continue
        api_key = str(provider.get("api_key") or "").strip()
        base_url = str(provider.get("base_url") or "").strip()
        if not base_url and route.lower() in LOCAL_PROXY_PROVIDER_ROUTES:
            base_url = DEFAULT_LOCAL_PROXY_BASE_URL
        if not api_key or not base_url:
            continue
        return {
            "mode": "inherit_ai",
            "route": route,
            "name": str(provider.get("name") or route).strip(),
            "type": str(provider.get("type") or "openai-compatible").strip() or "openai-compatible",
            "base_url": base_url,
            "api_key": api_key,
        }
    return None

def _resolve_special_provider_config_unlocked(
    *,
    kind: str,
    mode: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    route: str | None = None,
    provider_type: str | None = None,
):
    normalized_kind = _normalize_special_provider_kind(kind)
    settings = load_settings()
    normalized_mode = _normalize_special_provider_mode(mode, settings, normalized_kind)
    model_default = "FunAudioLLM/SenseVoiceSmall" if normalized_kind == "voice" else ""
    model = str(settings.get(f"{normalized_kind}_model") or model_default).strip()

    if normalized_mode == "inherit_ai":
        provider = _first_complete_ai_provider()
        if provider:
            resolved = {
                **provider,
                "kind": normalized_kind,
                "model": model,
                "complete": True,
                "missing": [],
            }
            return resolved
        resolved = {
            "kind": normalized_kind,
            "mode": "inherit_ai",
            "route": route or "",
            "name": "AI Provider",
            "type": provider_type or "openai-compatible",
            "base_url": "",
            "api_key": "",
            "model": model,
            "complete": False,
            "missing": [f"{normalized_kind}_base_url", f"{normalized_kind}_api_key"],
        }
        if not model:
            resolved["missing"].append(f"{normalized_kind}_model")
        return resolved

    saved_base_url = str(settings.get(f"{normalized_kind}_base_url") or "").strip()
    resolved_base_url = str(base_url or saved_base_url).strip()
    resolved_api_key = _destination_bound_api_key(
        api_key, resolved_base_url, settings.get(f"{normalized_kind}_api_key"), saved_base_url,
    )
    resolved_type = str(provider_type or "openai-compatible").strip() or "openai-compatible"
    resolved_route = str(route or normalized_kind).strip() or normalized_kind
    missing = []
    if not resolved_base_url:
        missing.append(f"{normalized_kind}_base_url")
    if not resolved_api_key:
        missing.append(f"{normalized_kind}_api_key")
    if not model:
        missing.append(f"{normalized_kind}_model")
    return {
        "kind": normalized_kind,
        "mode": "custom",
        "route": resolved_route,
        "name": "Voice Provider" if normalized_kind == "voice" else "Image Provider",
        "type": resolved_type,
        "base_url": resolved_base_url,
        "api_key": resolved_api_key,
        "model": model,
        "complete": not missing,
        "missing": missing,
    }

def _resolve_special_provider_config(
    *,
    kind: str,
    mode: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    route: str | None = None,
    provider_type: str | None = None,
):
    with _settings._automation_config_lock:
        return _resolve_special_provider_config_unlocked(
            kind=kind,
            mode=mode,
            base_url=base_url,
            api_key=api_key,
            route=route,
            provider_type=provider_type,
        )

def _safe_resolved_provider_payload(provider_config: dict) -> dict:
    return {
        "kind": provider_config.get("kind"),
        "mode": provider_config.get("mode"),
        "route": provider_config.get("route"),
        "name": provider_config.get("name"),
        "base_url": provider_config.get("base_url"),
    }

def _redact_subprocess_command_for_log(cmd, *, api_key: str | None = None) -> str:
    redacted_parts = []
    redact_next = False
    sensitive_flags = {"--transcribe-api-key"}
    for part in cmd:
        text = str(part)
        if redact_next:
            redacted_parts.append("[REDACTED_API_KEY]")
            redact_next = False
            continue
        if any(text.startswith(f"{flag}=") for flag in sensitive_flags):
            flag, _separator, _value = text.partition("=")
            redacted_parts.append(f"{flag}=[REDACTED_API_KEY]")
            continue
        redacted_parts.append(_redact_api_key_from_message(text, api_key))
        if text in sensitive_flags:
            redact_next = True
    return " ".join(redacted_parts)

@router.post("/api/v1/providers/models/discover")
async def discover_provider_models(request: ProviderModelDiscoverRequest):
    resolved = await asyncio.to_thread(
        _resolve_special_provider_config,
        kind=request.kind,
        mode=request.mode,
        base_url=request.base_url,
        api_key=request.api_key,
        route=request.route,
        provider_type=request.type,
    )
    if not resolved.get("base_url") or not resolved.get("api_key"):
        return JSONResponse(
            status_code=400,
            content={
                "models": [],
                "model_capabilities": {},
                "error": "Provider Base URL and API key are required for model discovery.",
                "resolved_provider": _safe_resolved_provider_payload(resolved),
                "missing": resolved.get("missing") or [],
            },
        )

    try:
        payload = await asyncio.to_thread(
            LLMClient.discover_models_for_config,
            route=resolved["route"],
            base_url=resolved["base_url"],
            api_key=resolved["api_key"],
            provider_type=resolved["type"],
        )
        return {
            **payload,
            "resolved_provider": _safe_resolved_provider_payload(resolved),
        }
    except Exception as error:
        error_message = _redact_api_key_from_message(str(error), resolved["api_key"])
        return JSONResponse(
            status_code=400,
            content={
                "models": [],
                "model_capabilities": {},
                "error": error_message,
                "resolved_provider": _safe_resolved_provider_payload(resolved),
            },
        )

@router.post("/api/v1/models/discover")
async def discover_llm_models(request: LLMModelDiscoverRequest):
    resolved = await asyncio.to_thread(_resolve_discover_secret, request)
    try:
        payload = await asyncio.to_thread(
            LLMClient.discover_models_for_config,
            route=resolved["route"],
            base_url=resolved["base_url"],
            api_key=resolved["api_key"],
            provider_type=resolved["type"],
        )
        return payload
    except Exception as error:
        error_message = _redact_api_key_from_message(str(error), resolved["api_key"])
        return JSONResponse(
            status_code=400,
            content={
                "models": [],
                "model_capabilities": {},
                "error": error_message,
            },
        )

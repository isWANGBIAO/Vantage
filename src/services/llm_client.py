import copy
import hashlib
import json
import logging
import re
import time
import uuid
from datetime import datetime

import requests

from src.core.config import Config
from src.core import user_config
from src.services.model_call_recorder import SessionRecorder
from src.utils.sensitive_data import redact_sensitive_text

SYNC_REQUEST_TIMEOUT_SECONDS = 1200
STREAM_REQUEST_TIMEOUT_SECONDS = 600
PRIMARY_TRANSIENT_RETRY_COUNT = 5
LOCAL_PROVIDER_RETRY_DELAY_SECONDS = 1.0
ACTIVE_CACHE_REQUEST_KEYS = {
    "prompt_cache_key",
    "prompt_cache_retention",
    "cache_control",
}
FAST_SERVICE_TIER_VALUE = "priority"
FAST_SERVICE_TIER_ALIASES = {"priority", "fast"}
FAST_SERVICE_TIER_MODELS = {"gpt-5.5", "gpt-5.4", "gpt-5.4-mini"}
NORMAL_STREAM_FINISH_REASONS = {"stop", "tool_calls", "function_call"}


def _hash_json_payload(value):
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _drop_active_cache_fields(value):
    if isinstance(value, dict):
        return {
            key: _drop_active_cache_fields(item)
            for key, item in value.items()
            if key not in ACTIVE_CACHE_REQUEST_KEYS
        }
    if isinstance(value, list):
        return [_drop_active_cache_fields(item) for item in value]
    return value


class StreamIncompleteError(RuntimeError):
    """Raised when an SSE model stream ends without a trustworthy terminal event."""


class LLMClient:
    def __init__(self):
        Config.load_env()
        self.providers = self._build_provider_chain()

    def _provider_from_env(
        self,
        *,
        route,
        base_url_key,
        api_key_key,
        model_key,
        default_base_url=None,
        require_model=True,
    ):
        base_url = Config.get(base_url_key, default_base_url)
        api_key = Config.get(api_key_key)
        model = Config.get(model_key)

        if not api_key and not model:
            return None
        if not api_key:
            raise ValueError(f"Missing environment variable: {api_key_key}")
        if not model and require_model:
            raise ValueError(f"Missing environment variable: {model_key}")
        if not base_url:
            raise ValueError(f"Missing environment variable: {base_url_key}")

        models = [model] if model else []
        return {
            "route": route,
            "base_url": base_url.rstrip("/"),
            "model": model or "",
            "models": models,
            "headers": self._build_headers(api_key),
        }

    def _model_version_key(self, model_id):
        match = re.match(
            r"^gpt-(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-(.+))?$",
            model_id.lower(),
        )
        if not match:
            return None
        major, minor, patch, suffix = match.groups()
        suffix_key = (suffix or "").lower()
        is_code_variant = "code" in suffix_key or "codex" in suffix_key
        if not suffix_key:
            family_rank = 3
        elif suffix_key.startswith("mini"):
            family_rank = 2
        elif is_code_variant:
            family_rank = 0
        else:
            family_rank = 1
        return (
            int(major),
            int(minor or -1),
            int(patch or -1),
            family_rank,
        )

    def _normalize_parameter_name(self, name):
        return str(name).strip().lower().replace("-", "_")

    def _normalize_model_alias(self, model_id):
        normalized = str(model_id or "").strip().lower()
        for prefix in ("pro/", "free/"):
            if normalized.startswith(prefix):
                return normalized[len(prefix):]
        return normalized

    def _models_match(self, left_model, right_model):
        left = str(left_model or "").strip()
        right = str(right_model or "").strip()
        if not left or not right:
            return False
        return left == right or self._normalize_model_alias(left) == self._normalize_model_alias(right)

    def _extract_supported_parameters(self, model_item):
        if not isinstance(model_item, dict):
            return None

        for key in ("supported_parameters", "supportedParameters", "parameters"):
            raw = model_item.get(key)
            if raw:
                return self._normalize_supported_parameters(raw)

        metadata = model_item.get("metadata")
        if isinstance(metadata, dict):
            for key in ("supported_parameters", "supportedParameters", "parameters"):
                raw = metadata.get(key)
                if raw:
                    return self._normalize_supported_parameters(raw)

        return None

    def _normalize_supported_parameters(self, raw_parameters):
        if raw_parameters is None:
            return None
        if isinstance(raw_parameters, dict):
            raw_parameters = [name for name, enabled in raw_parameters.items() if bool(enabled)]
        if not isinstance(raw_parameters, (list, tuple, set)):
            return None

        normalized = set()
        for item in raw_parameters:
            if not isinstance(item, str):
                continue
            parameter = self._normalize_parameter_name(item)
            if not parameter:
                continue
            normalized.add(parameter)

        return normalized

    def _supports_reasoning_parameter(self, supported_parameters):
        if supported_parameters is None:
            return True
        if "reasoning_effort" in supported_parameters:
            return True
        return any(
            parameter in {"reasoning", "reasoning_effort"}
            or parameter.startswith("reasoning_")
            for parameter in supported_parameters
        )

    def _supports_service_tier_parameter(self, supported_parameters):
        if supported_parameters is None:
            return True
        return "service_tier" in supported_parameters

    def _can_model_use_reasoning(self, provider, model):
        model_capabilities = provider.get("model_capabilities")
        if not isinstance(model_capabilities, dict):
            return True

        supported_parameters = model_capabilities.get(model)
        if supported_parameters is None:
            return True

        return self._supports_reasoning_parameter(supported_parameters)

    def _can_model_use_service_tier(self, provider, model):
        model_capabilities = provider.get("model_capabilities")
        if not isinstance(model_capabilities, dict):
            return True

        supported_parameters = model_capabilities.get(model)
        if supported_parameters is None:
            return True

        return self._supports_service_tier_parameter(supported_parameters)

    def _is_fast_service_tier_model(self, model):
        return self._normalize_model_alias(model) in FAST_SERVICE_TIER_MODELS

    def _normalize_service_tier_for_model(self, provider, model, service_tier):
        normalized_tier = str(service_tier or "").strip().lower()
        if normalized_tier not in FAST_SERVICE_TIER_ALIASES:
            return None
        if not self._is_fast_service_tier_model(model):
            return None
        if not self._can_model_use_service_tier(provider or {}, model):
            return None
        return FAST_SERVICE_TIER_VALUE

    def _apply_model_capabilities_to_payload(self, payload, provider, model):
        if not isinstance(payload, dict):
            return payload

        filtered_payload = payload
        if "reasoning_effort" in filtered_payload and not self._can_model_use_reasoning(provider, model):
            filtered_payload = dict(filtered_payload)
            filtered_payload.pop("reasoning_effort", None)
            logging.info(
                "Model %s does not advertise reasoning_effort support on route %s, omitting parameter",
                model,
                provider.get("route"),
            )

        if "service_tier" in filtered_payload:
            effective_service_tier = self._normalize_service_tier_for_model(
                provider,
                model,
                filtered_payload.get("service_tier"),
            )
            if effective_service_tier:
                if effective_service_tier != filtered_payload.get("service_tier"):
                    filtered_payload = dict(filtered_payload)
                    filtered_payload["service_tier"] = effective_service_tier
            else:
                filtered_payload = dict(filtered_payload)
                filtered_payload.pop("service_tier", None)
                logging.info(
                    "Model %s on route %s does not use fast service tier, omitting parameter",
                    model,
                    provider.get("route"),
                )

        return filtered_payload

    def _is_siliconflow_deepseek_v32(self, provider, model):
        route = str((provider or {}).get("route") or "").strip().lower()
        normalized_model = self._normalize_model_alias(model)
        return route == "siliconflow_fallback" and normalized_model == "deepseek-ai/deepseek-v3.2"

    def _is_deepseek_v4_model(self, provider, model):
        normalized_model = str(model or "").strip().lower()
        provider_name = str((provider or {}).get("name") or "").strip().lower()
        provider_route = str((provider or {}).get("route") or "").strip().lower()
        return (
            normalized_model in {"deepseek-v4-pro", "deepseek-v4-flash"}
            or normalized_model.endswith("/deepseek-v4-pro")
            or normalized_model.endswith("/deepseek-v4-flash")
            or (
                "deepseek" in provider_name
                and normalized_model.startswith("deepseek-v4")
            )
            or (
                "deepseek" in provider_route
                and normalized_model.startswith("deepseek-v4")
            )
        )

    def _normalize_reasoning_effort_for_model(self, provider, model, reasoning_effort):
        normalized_effort = str(reasoning_effort or "").strip().lower()
        if self._is_deepseek_v4_model(provider, model):
            return "max" if normalized_effort in {"xhigh", "extra_high", "max"} else "high"
        if normalized_effort == "max":
            return "xhigh"
        if normalized_effort in {"low", "medium", "high", "xhigh"}:
            return normalized_effort
        return "medium"

    def _map_reasoning_effort_to_thinking_budget(self, reasoning_effort):
        budgets = {
            "low": 1024,
            "medium": 2048,
            "high": 4096,
            "xhigh": 8192,
            "max": 8192,
        }
        normalized_effort = str(reasoning_effort or "").strip().lower()
        return budgets.get(normalized_effort, budgets["medium"])

    def _apply_provider_payload_overrides(self, payload, provider, model):
        if not isinstance(payload, dict):
            return payload

        reasoning_effort = payload.get("reasoning_effort")
        if reasoning_effort:
            effective_effort = self._normalize_reasoning_effort_for_model(
                provider,
                model,
                reasoning_effort,
            )
            if effective_effort != reasoning_effort:
                payload = dict(payload)
                payload["reasoning_effort"] = effective_effort
                reasoning_effort = effective_effort

        if self._is_deepseek_v4_model(provider, model):
            adapted_payload = dict(payload)
            adapted_payload["reasoning_effort"] = self._normalize_reasoning_effort_for_model(
                provider,
                model,
                reasoning_effort,
            )
            adapted_payload["thinking"] = {"type": "enabled"}
            logging.info(
                "Adapted DeepSeek V4 thinking payload for model %s on route %s: reasoning_effort=%s thinking=%s",
                model,
                provider.get("route"),
                adapted_payload["reasoning_effort"],
                adapted_payload["thinking"],
            )
            return adapted_payload

        if not self._is_siliconflow_deepseek_v32(provider, model):
            return payload

        if not reasoning_effort:
            return payload

        adapted_payload = dict(payload)
        adapted_payload.pop("reasoning_effort", None)
        adapted_payload["enable_thinking"] = True
        adapted_payload["thinking_budget"] = self._map_reasoning_effort_to_thinking_budget(reasoning_effort)
        logging.info(
            "Adapted SiliconFlow thinking payload for model %s on route %s: enable_thinking=%s thinking_budget=%s",
            model,
            provider.get("route"),
            adapted_payload["enable_thinking"],
            adapted_payload["thinking_budget"],
        )
        return adapted_payload

    def _discover_primary_models(self, provider):
        url = provider["base_url"] + "/models"

        try:
            response = requests.get(url, headers=provider["headers"], timeout=10)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as error:
            logging.warning(
                "Failed to discover CLIProxyAPI models at %s: %s",
                provider["base_url"],
                str(error),
            )
            return []

        candidates = []
        for item in payload.get("data", []):
            if not isinstance(item, dict):
                continue

            model_id = str(item.get("id", "")).strip()
            if not model_id:
                model_id = str(item.get("name", "")).strip()
            if not model_id:
                continue

            version_key = self._model_version_key(model_id)
            supported_parameters = self._extract_supported_parameters(item)
            if version_key is None:
                # Keep non-standard aliases in the catalog instead of dropping them.
                # This makes custom aliases (including provider-prefix forms) visible in UI
                # and usable for manual override.
                sort_key = (0, 0, 0, 0, 0)
            else:
                # Preserve existing version-priority behavior for standard GPT-family ids.
                major, minor, patch, family_rank = version_key
                sort_key = (1, major, minor, patch, family_rank)

            candidates.append((sort_key, model_id, supported_parameters))

        # Keep latest/most specific versions first, then fall back to other aliases.
        candidates.sort(reverse=True)
        return [
            {
                "id": model_id,
                "supported_parameters": supported_parameters,
            }
            for _, model_id, supported_parameters in candidates
        ]

    @classmethod
    def discover_models_for_config(cls, *, route, base_url, api_key, provider_type="openai-compatible"):
        normalized_base_url = str(base_url or "").strip().rstrip("/")
        normalized_api_key = str(api_key or "").strip()
        normalized_route = str(route or "").strip() or "custom"
        normalized_type = str(provider_type or "").strip() or "openai-compatible"
        if normalized_type != "openai-compatible":
            raise ValueError("Only OpenAI-compatible providers are supported in this version.")
        if not normalized_base_url:
            raise ValueError("Base URL is required for model discovery.")
        if not normalized_api_key:
            raise ValueError("API Key is required for model discovery.")

        helper = cls.__new__(cls)
        provider = {
            "route": normalized_route,
            "base_url": normalized_base_url,
            "model": "",
            "models": [],
            "headers": helper._build_headers(normalized_api_key),
        }
        discovered = helper._discover_primary_models(provider)
        return {
            "models": [item["id"] for item in discovered],
            "model_capabilities": {
                item["id"]: sorted(item["supported_parameters"]) if isinstance(item.get("supported_parameters"), set) else item.get("supported_parameters")
                for item in discovered
            },
            "error": None if discovered else "No models returned by provider.",
        }

    def _provider_from_user_config(self, user_provider):
        model = str(user_provider.get("model") or "").strip()
        models = [str(item).strip() for item in (user_provider.get("models") or []) if str(item or "").strip()]
        if model and model not in models:
            models = [model, *models]
        if not model and models:
            model = models[0]

        provider = {
            "route": user_provider["route"],
            "name": user_provider.get("name") or user_provider["route"],
            "type": user_provider.get("type") or "openai-compatible",
            "base_url": user_provider["base_url"].rstrip("/"),
            "model": model,
            "models": models,
            "headers": self._build_headers(user_provider["api_key"]),
            "model_capabilities": {model_id: None for model_id in models},
        }
        if not provider["model"]:
            discovered_models = self._discover_primary_models(provider)
            if discovered_models:
                provider["model"] = discovered_models[0]["id"]
                provider["models"] = [model_info["id"] for model_info in discovered_models]
                provider["model_capabilities"] = {
                    model_info["id"]: model_info.get("supported_parameters")
                    for model_info in discovered_models
                }
                logging.info(
                    "Auto-selected user provider model %s for route %s from candidates: %s",
                    provider["model"],
                    provider["route"],
                    ", ".join(model_info["id"] for model_info in discovered_models),
                )

        if not provider["model"]:
            raise ValueError(
                f"Provider {provider['route']} has no configured model and model discovery returned no models. "
                "Configure a model in Settings."
            )

        if not provider["models"]:
            provider["models"] = [provider["model"]]
            provider["model_capabilities"] = {provider["model"]: None}
        elif provider["model"] not in provider["models"]:
            provider["models"] = [provider["model"], *provider["models"]]
            provider["model_capabilities"].setdefault(provider["model"], None)

        return provider

    def _build_provider_chain(self):
        user_providers = user_config.get_provider_chain_config()
        if user_providers:
            providers = [self._provider_from_user_config(provider) for provider in user_providers]
            logging.info(
                "Configured user LLM provider chain: %s",
                " -> ".join(f"{provider['route']}({provider['model']})" for provider in providers),
            )
            return providers

        providers = []

        primary = self._provider_from_env(
            route="cliproxyapi_primary",
            base_url_key="CLIPROXYAPI_BASE_URL",
            api_key_key="CLIPROXYAPI_API_KEY",
            model_key="CLIPROXYAPI_MODEL",
            default_base_url="http://127.0.0.1:8317/v1",
            require_model=False,
        )
        if not primary:
            raise ValueError("Missing environment variables: CLIPROXYAPI_API_KEY and CLIPROXYAPI_MODEL")
        discovered_models = self._discover_primary_models(primary)
        if discovered_models:
            primary["model"] = discovered_models[0]["id"]
            primary["models"] = [model_info["id"] for model_info in discovered_models]
            primary["model_capabilities"] = {
                model_info["id"]: model_info.get("supported_parameters")
                for model_info in discovered_models
            }
            logging.info(
                "Auto-selected CLIProxyAPI primary model %s from candidates: %s",
                primary["model"],
                ", ".join(model_info["id"] for model_info in discovered_models),
            )
        else:
            if not primary["model"]:
                raise ValueError(
                    "Missing CLIPROXYAPI_MODEL and CLIProxyAPI model discovery returned no models. "
                    "Configure a model in Settings or set CLIPROXYAPI_MODEL."
                )
            logging.info(
                "CLIProxyAPI model discovery unavailable; using configured primary model %s",
                primary["model"],
            )
            primary["model_capabilities"] = {primary["model"]: None}
        providers.append(primary)

        secondary = self._provider_from_env(
            route="cliproxyapi_secondary",
            base_url_key="CLIPROXYAPI_SECONDARY_BASE_URL",
            api_key_key="CLIPROXYAPI_SECONDARY_API_KEY",
            model_key="CLIPROXYAPI_SECONDARY_MODEL",
            default_base_url="http://127.0.0.1:8045/v1",
        )
        if secondary:
            secondary["model_capabilities"] = {secondary["model"]: None}
            providers.append(secondary)

        fallback = self._provider_from_env(
            route="siliconflow_fallback",
            base_url_key="CLIPROXYAPI_FALLBACK_BASE_URL",
            api_key_key="CLIPROXYAPI_FALLBACK_API_KEY",
            model_key="CLIPROXYAPI_FALLBACK_MODEL",
            default_base_url="https://api.siliconflow.cn/v1",
        )
        if fallback:
            fallback["model_capabilities"] = {fallback["model"]: None}
            providers.append(fallback)

        logging.info(
            "Configured LLM provider chain: %s",
            " -> ".join(f"{provider['route']}({provider['model']})" for provider in providers),
        )
        return providers

    def _build_headers(self, api_key):
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _apply_model_settings(self, payload, model):
        updated = dict(payload)
        updated["model"] = model
        return updated

    def _known_secret_values(self):
        secrets = []
        for provider in getattr(self, "providers", []) or []:
            auth_header = provider.get("headers", {}).get("Authorization")
            if isinstance(auth_header, str) and auth_header.startswith("Bearer "):
                secret = auth_header[len("Bearer "):].strip()
                if secret:
                    secrets.append(secret)
        return secrets

    def _redact_secrets(self, text):
        if not isinstance(text, str):
            return text

        redacted = text
        for secret in self._known_secret_values():
            redacted = redacted.replace(secret, "[REDACTED_API_KEY]")
        return redact_sensitive_text(redacted)

    def _describe_request_error(self, error):
        response = getattr(error, "response", None)
        if response is None:
            return self._redact_secrets(str(error))

        details = ""
        try:
            details = response.text.strip()
        except Exception:
            details = ""

        if details:
            return self._redact_secrets(f"{error} | body={details[:500]}")
        return self._redact_secrets(str(error))

    def _is_model_compatibility_error(self, details):
        text = details.lower()
        return (
            "unknown provider for model" in text
            or "model is not supported" in text
            or "model not supported" in text
            or "unsupported" in text
        )

    def _is_local_provider(self, provider):
        base_url = str((provider or {}).get("base_url") or "").strip().lower()
        return (
            "://127.0.0.1" in base_url
            or "://localhost" in base_url
            or "://[::1]" in base_url
        )

    def _is_retryable_provider_error(self, provider, details):
        if provider.get("route") != "cliproxyapi_primary" and not self._is_local_provider(provider):
            return False

        text = details.lower()
        return (
            "unexpected eof" in text
            or ": eof" in text
            or "remote end closed connection" in text
            or "connection aborted" in text
            or "read timed out" in text
            or "failed to establish a new connection" in text
            or "connection refused" in text
            or "actively refused" in text
            or "winerror 10061" in text
            or "newconnectionerror" in text
            or "max retries exceeded" in text
        )

    def _retry_delay_seconds(self, provider, details):
        if not self._is_local_provider(provider):
            return 0

        text = details.lower()
        if (
            "failed to establish a new connection" in text
            or "connection refused" in text
            or "actively refused" in text
            or "winerror 10061" in text
            or "newconnectionerror" in text
            or "max retries exceeded" in text
        ):
            return LOCAL_PROVIDER_RETRY_DELAY_SECONDS

        return 0

    def _provider_with_requested_model_first(self, provider, requested_model):
        provider_snapshot = dict(provider)
        models = [str(model) for model in (provider.get("models") or [provider.get("model")]) if model]
        requested_model = (requested_model or "").strip()
        if requested_model:
            matched_model = next(
                (candidate for candidate in models if self._models_match(candidate, requested_model)),
                requested_model,
            )
            provider_snapshot["models"] = [matched_model] + [model for model in models if model != matched_model]
            return provider_snapshot

        provider_snapshot["models"] = models
        return provider_snapshot

    def _ordered_providers(self, requested_model, requested_provider_route=None):
        requested_model = (requested_model or "").strip()
        requested_provider_route = (requested_provider_route or "").strip()

        if requested_provider_route:
            prioritized = []
            fallback = []
            for provider in self.providers:
                if provider.get("route") == requested_provider_route:
                    prioritized.append(self._provider_with_requested_model_first(provider, requested_model))
                else:
                    fallback.append(self._provider_with_requested_model_first(provider, None))
            return prioritized + fallback

        if not requested_model:
            return self.providers

        prioritized = []
        fallback = []

        for provider in self.providers:
            models = [str(model) for model in (provider.get("models") or [provider.get("model")]) if model]
            matched_model = next(
                (candidate for candidate in models if self._models_match(candidate, requested_model)),
                None,
            )
            if matched_model:
                provider_snapshot = self._provider_with_requested_model_first(provider, matched_model)
                prioritized.append(provider_snapshot)
            else:
                fallback.append(provider)

        return prioritized + fallback

    def get_model_catalog(self):
        catalog = []

        for provider in self.providers:
            models = [str(model) for model in (provider.get("models") or [provider.get("model")]) if model]
            seen = set()
            normalized_models = []
            for model in models:
                if model in seen:
                    continue
                seen.add(model)
                normalized_models.append(model)

            raw_capabilities = provider.get("model_capabilities", {})
            model_capabilities = {}
            if isinstance(raw_capabilities, dict):
                for model in normalized_models:
                    supported = raw_capabilities.get(model)
                    if supported is None:
                        model_capabilities[model] = None
                        continue
                    if isinstance(supported, set):
                        model_capabilities[model] = sorted(supported)
                    elif isinstance(supported, (list, tuple)):
                        model_capabilities[model] = list(supported)
                    else:
                        model_capabilities[model] = None

            catalog.append({
                "route": provider["route"],
                "name": provider.get("name") or provider["route"],
                "type": provider.get("type") or "openai-compatible",
                "model": provider["model"],
                "models": normalized_models,
                "base_url": provider["base_url"],
                "model_capabilities": model_capabilities,
            })

        return catalog

    def _post_with_failover(self, payload, stream=False, timeout=120, requested_model=None, requested_provider_route=None):
        provider_chain = self._ordered_providers(requested_model, requested_provider_route)
        errors = []

        for provider in provider_chain:
            url = provider["base_url"] + "/chat/completions"
            model_candidates = list(provider.get("models") or [provider["model"]])

            for index, model in enumerate(model_candidates):
                provider_payload = self._apply_model_capabilities_to_payload(
                    self._apply_provider_payload_overrides(
                        self._apply_model_settings(payload, model),
                        provider,
                        model,
                    ),
                    provider,
                    model,
                )
                should_try_next_model = False
                retry_count = 0

                while True:
                    try:
                        response = requests.post(
                            url,
                            json=provider_payload,
                            headers=provider["headers"],
                            timeout=timeout,
                            stream=stream,
                        )
                        response.raise_for_status()
                        provider["model"] = model
                        provider["models"] = [model] + [candidate for candidate in model_candidates if candidate != model]
                        logging.info(
                            "LLM route %s succeeded with model %s at %s",
                            provider["route"],
                            model,
                            provider["base_url"],
                        )
                        return response, model, provider["route"]
                    except requests.RequestException as error:
                        details = self._describe_request_error(error)
                        errors.append(f"{provider['route']}[{model}]: {details}")
                        logging.warning(
                            "LLM route %s failed for model %s at %s: %s",
                            provider["route"],
                            model,
                            provider["base_url"],
                            details,
                        )
                        if retry_count < PRIMARY_TRANSIENT_RETRY_COUNT and self._is_retryable_provider_error(provider, details):
                            retry_count += 1
                            logging.info(
                                "Retrying LLM route %s with model %s after transient upstream error",
                                provider["route"],
                                model,
                            )
                            delay_seconds = self._retry_delay_seconds(provider, details)
                            if delay_seconds > 0:
                                time.sleep(delay_seconds)
                            continue

                        has_next_model = index + 1 < len(model_candidates)
                        if has_next_model and self._is_model_compatibility_error(details):
                            should_try_next_model = True
                        break

                if should_try_next_model:
                        continue
                break

        raise requests.RequestException("All LLM providers failed: " + " | ".join(errors))

    def _find_provider(self, route):
        normalized_route = str(route or "").strip()
        if not normalized_route:
            return None
        return next((provider for provider in self.providers if provider.get("route") == normalized_route), None)

    def _resolve_requested_provider(self, provider_route=None):
        provider = self._find_provider(provider_route)
        if provider:
            return provider
        return self.providers[0] if self.providers else None

    def _effective_reasoning_effort_for_result(self, provider_route, model, reasoning_effort):
        provider = self._find_provider(provider_route) or {"route": provider_route}
        return self._normalize_reasoning_effort_for_model(provider, model, reasoning_effort)

    def _effective_service_tier_for_result(self, provider_route, model, service_tier):
        provider = self._find_provider(provider_route) or {"route": provider_route}
        return self._normalize_service_tier_for_model(provider, model, service_tier)

    def _is_fallback_result(self, requested_model, requested_route, used_model, used_route):
        return bool(
            (requested_model and used_model and not self._models_match(requested_model, used_model))
            or (requested_route and used_route and requested_route != used_route)
        )

    def chat(
        self,
        messages,
        stream=True,
        print_callback=None,
        model=None,
        provider_route=None,
        session_id=None,
        source="llm_client",
        entrypoint="src/services/llm_client.py",
        context_file=None,
        history_dir=None,
        metadata=None,
        reasoning_effort=None,
        service_tier=None,
    ):
        """
        Send chat request to LLM.

        Args:
            messages: List of message dicts.
            stream: Whether to stream the response.
            print_callback: Function(tag, content) to handle stream output.
        """
        messages = copy.deepcopy(messages)

        if isinstance(model, dict):
            raise TypeError("model override must be a string when provided")

        reasoning_effort = reasoning_effort or Config.get("AI_REASONING_EFFORT") or "medium"
        request_metadata = dict(metadata or {})
        stable_prefix_messages = messages[:-1] if messages else []
        request_metadata.setdefault("sent_context_message_count", len(messages))
        request_metadata.setdefault("stable_prefix_message_count", len(stable_prefix_messages))
        request_metadata["stable_prefix_hash"] = _hash_json_payload(stable_prefix_messages)
        request_metadata["full_prompt_hash"] = _hash_json_payload(messages)

        requested_provider = self._resolve_requested_provider(provider_route)
        requested_model = model or (requested_provider["model"] if requested_provider else None)
        requested_route = requested_provider["route"] if requested_provider else None
        requested_base_url = requested_provider["base_url"] if requested_provider else None
        effective_service_tier = self._normalize_service_tier_for_model(
            requested_provider or {},
            requested_model,
            service_tier,
        )
        request_metadata["requested_model"] = requested_model
        request_metadata["requested_provider_route"] = requested_route
        request_metadata["requested_service_tier"] = str(service_tier).strip().lower() if service_tier else None
        request_metadata["service_tier"] = effective_service_tier

        payload = _drop_active_cache_fields({
            "messages": messages,
            "stream": stream,
            "temperature": float(Config.get("AI_TEMPERATURE", 0.6)),
            "top_p": 0.7,
            "frequency_penalty": 0.5,
            "n": 1,
        })
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if effective_service_tier:
            payload["service_tier"] = effective_service_tier
        call_id = str(uuid.uuid4())
        recorder = self._build_session_recorder(
            session_id=session_id,
            source=source,
            entrypoint=entrypoint,
            context_file=context_file,
            history_dir=history_dir,
            default_model=requested_model,
            provider_route=requested_route,
            base_url=requested_base_url,
        )

        self._record_call_start(
            recorder=recorder,
            call_id=call_id,
            messages=messages,
            model=requested_model,
            provider_route=requested_route,
            stream=stream,
            reasoning_effort=reasoning_effort,
            service_tier=effective_service_tier,
            metadata=request_metadata,
        )

        start_time = time.time()

        if stream:
            return self._handle_stream(
                payload,
                start_time,
                print_callback,
                reasoning_effort,
                model,
                recorder,
                call_id,
                requested_model,
                requested_route,
                service_tier,
            )
        return self._handle_sync(
            payload,
            start_time,
            reasoning_effort,
            model,
            recorder,
            call_id,
            requested_model,
            requested_route,
            service_tier,
        )

    def _build_session_recorder(
        self,
        *,
        session_id,
        source,
        entrypoint,
        context_file,
        history_dir,
        default_model,
        provider_route,
        base_url,
    ):
        try:
            return SessionRecorder(
                session_id=session_id,
                source=source or "llm_client",
                entrypoint=entrypoint or "src/services/llm_client.py",
                history_dir=history_dir,
                context_file=context_file,
                default_model=default_model,
                provider_route=provider_route,
                base_url=base_url,
            )
        except Exception as error:
            logging.error("Failed to initialize SessionRecorder: %s", error)
            return None

    def _safe_record(self, recorder, method_name, **kwargs):
        if recorder is None:
            return
        try:
            getattr(recorder, method_name)(**kwargs)
        except Exception as error:
            logging.error("Failed to persist model call via SessionRecorder.%s: %s", method_name, error)

    def _record_call_start(
        self,
        *,
        recorder,
        call_id,
        messages,
        model,
        provider_route,
        stream,
        reasoning_effort,
        service_tier,
        metadata,
    ):
        self._safe_record(
            recorder,
            "record_request_started",
            call_id=call_id,
            model=model,
            provider_route=provider_route,
            stream=stream,
            reasoning_effort=reasoning_effort,
            service_tier=service_tier,
            messages=None,
            metadata=metadata,
        )
        self._safe_record(
            recorder,
            "record_message_snapshot",
            call_id=call_id,
            messages=messages,
        )

    def _extract_content(self, message):
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            return "".join(text_parts)
        return ""

    def _handle_sync(
        self,
        payload,
        start_time,
        reasoning_effort,
        model=None,
        recorder=None,
        call_id=None,
        requested_model=None,
        requested_route=None,
        service_tier=None,
    ):
        try:
            response, used_model, used_route = self._post_with_failover(
                payload,
                stream=False,
                timeout=SYNC_REQUEST_TIMEOUT_SECONDS,
                requested_model=model,
                requested_provider_route=requested_route,
            )
            data = response.json()

            message = data["choices"][0]["message"]
            usage = data.get("usage", {})
            duration = time.time() - start_time
            effective_reasoning_effort = self._effective_reasoning_effort_for_result(
                used_route,
                used_model,
                reasoning_effort,
            )
            effective_service_tier = self._effective_service_tier_for_result(
                used_route,
                used_model,
                service_tier,
            )

            result = {
                "content": self._extract_content(message),
                "thinking": message.get("reasoning_content") or "",
                "usage": usage,
                "duration": duration,
                "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "first_token_latency": None,
                "model": used_model,
                "provider_route": used_route,
                "requested_model": requested_model,
                "requested_provider_route": requested_route,
                "fallback_used": self._is_fallback_result(requested_model, requested_route, used_model, used_route),
                "reasoning_effort": effective_reasoning_effort,
                "service_tier": effective_service_tier,
            }
            self._safe_record(
                recorder,
                "record_request_completed",
                call_id=call_id,
                model=used_model,
                provider_route=used_route,
                stream=False,
                reasoning_effort=effective_reasoning_effort,
                service_tier=effective_service_tier,
                content=result["content"],
                thinking=result["thinking"],
                usage=result["usage"],
                response=data,
                duration=result["duration"],
                first_token_latency=result["first_token_latency"],
            )
            self._safe_record(
                recorder,
                "record_token_count",
                call_id=call_id,
                last_token_usage=result["usage"],
            )
            return result
        except Exception as error:
            self._safe_record(
                recorder,
                "record_request_failed",
                call_id=call_id,
                error=error,
                model=requested_model,
                provider_route=requested_route,
                stream=False,
                reasoning_effort=reasoning_effort,
                service_tier=self._effective_service_tier_for_result(requested_route, requested_model, service_tier),
                duration=time.time() - start_time,
            )
            raise

    def _handle_stream(
        self,
        payload,
        start_time,
        print_callback,
        reasoning_effort,
        model=None,
        recorder=None,
        call_id=None,
        requested_model=None,
        requested_route=None,
        service_tier=None,
    ):
        full_content = ""
        full_thinking = ""
        usage_data = {}
        used_model = requested_model
        used_route = requested_route
        first_token_latency = None
        saw_done_event = False
        finish_reasons = []
        native_finish_reasons = []

        def mark_first_token():
            nonlocal first_token_latency
            if first_token_latency is None:
                first_token_latency = time.time() - start_time

        def output(tag, content):
            if print_callback:
                print_callback(tag, content)
            else:
                if tag == "thinking":
                    print(f"STREAM_THINKING:{json.dumps(content)}", flush=True)
                elif tag == "content":
                    print(f"STREAM_CONTENT:{json.dumps(content)}", flush=True)
                elif tag == "error":
                    print(f"STREAM_ERROR:{json.dumps(content)}", flush=True)

        try:
            response, used_model, used_route = self._post_with_failover(
                payload,
                stream=True,
                timeout=STREAM_REQUEST_TIMEOUT_SECONDS,
                requested_model=model,
                requested_provider_route=requested_route,
            )
            effective_reasoning_effort = self._effective_reasoning_effort_for_result(
                used_route,
                used_model,
                reasoning_effort,
            )
            effective_service_tier = self._effective_service_tier_for_result(
                used_route,
                used_model,
                service_tier,
            )

            metadata_event = {
                "model": used_model,
                "provider_route": used_route,
                "requested_model": requested_model,
                "requested_provider_route": requested_route,
                "fallback_used": self._is_fallback_result(requested_model, requested_route, used_model, used_route),
                "reasoning_effort": effective_reasoning_effort,
            }
            if effective_service_tier:
                metadata_event["service_tier"] = effective_service_tier
            output("metadata", metadata_event)

            for line in response.iter_lines(chunk_size=1):
                if not line:
                    continue
                line_str = line.decode("utf-8")

                if line_str.startswith("data: "):
                    data_str = line_str[6:]
                    if data_str.strip() == "[DONE]":
                        saw_done_event = True
                        if print_callback:
                            print_callback("done", "")
                        break

                    try:
                        data = json.loads(data_str)
                        self._safe_record(
                            recorder,
                            "record_response_chunk",
                            call_id=call_id,
                            chunk=data,
                        )
                        if "usage" in data:
                            usage_data = data["usage"]

                        if "choices" in data and len(data["choices"]) > 0:
                            choice = data["choices"][0]
                            finish_reason = choice.get("finish_reason")
                            native_finish_reason = choice.get("native_finish_reason")
                            if finish_reason:
                                finish_reasons.append(str(finish_reason))
                            if native_finish_reason:
                                native_finish_reasons.append(str(native_finish_reason))

                            delta = choice.get("delta", {})

                            reasoning = delta.get("reasoning_content", "")
                            if reasoning:
                                mark_first_token()
                                full_thinking += reasoning
                                output("thinking", reasoning)

                            content = delta.get("content", "")
                            if content:
                                mark_first_token()
                                full_content += content
                                output("content", content)
                    except json.JSONDecodeError:
                        continue

            observed_finish_reasons = [
                str(reason).strip().lower()
                for reason in [*finish_reasons, *native_finish_reasons]
                if str(reason).strip()
            ]
            abnormal_finish_reasons = [
                reason
                for reason in observed_finish_reasons
                if reason not in NORMAL_STREAM_FINISH_REASONS
            ]
            has_normal_finish_reason = any(
                reason in NORMAL_STREAM_FINISH_REASONS
                for reason in observed_finish_reasons
            )
            if abnormal_finish_reasons:
                raise StreamIncompleteError(
                    "Streaming response ended with incomplete finish_reason="
                    + ",".join(abnormal_finish_reasons)
                )
            if not saw_done_event and not has_normal_finish_reason:
                raise StreamIncompleteError(
                    "Streaming response ended without a terminal event "
                    f"(content_chars={len(full_content)}, thinking_chars={len(full_thinking)})"
                )

        except Exception as error:
            self._safe_record(
                recorder,
                "record_request_failed",
                call_id=call_id,
                error=error,
                model=used_model,
                provider_route=used_route,
                stream=True,
                reasoning_effort=reasoning_effort,
                service_tier=self._effective_service_tier_for_result(used_route, used_model, service_tier),
                duration=time.time() - start_time,
            )
            output("error", self._redact_secrets(str(error)))
            raise

        duration = time.time() - start_time
        effective_reasoning_effort = self._effective_reasoning_effort_for_result(
            used_route,
            used_model,
            reasoning_effort,
        )
        effective_service_tier = self._effective_service_tier_for_result(
            used_route,
            used_model,
            service_tier,
        )

        result = {
            "content": full_content,
            "thinking": full_thinking,
            "usage": usage_data or {},
            "duration": duration,
            "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "first_token_latency": first_token_latency,
            "model": used_model,
            "provider_route": used_route,
            "requested_model": requested_model,
            "requested_provider_route": requested_route,
            "fallback_used": self._is_fallback_result(requested_model, requested_route, used_model, used_route),
            "reasoning_effort": effective_reasoning_effort,
            "service_tier": effective_service_tier,
        }
        self._safe_record(
            recorder,
            "record_request_completed",
            call_id=call_id,
            model=used_model,
            provider_route=used_route,
            stream=True,
            reasoning_effort=effective_reasoning_effort,
            service_tier=effective_service_tier,
            content=result["content"],
            thinking=result["thinking"],
            usage=result["usage"],
            duration=result["duration"],
            first_token_latency=result["first_token_latency"],
        )
        self._safe_record(
            recorder,
            "record_token_count",
            call_id=call_id,
            last_token_usage=result["usage"],
        )
        return result


# Backward-compatible alias for older imports.
SiliconFlowClient = LLMClient

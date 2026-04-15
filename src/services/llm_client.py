import copy
import json
import logging
import re
import time

import requests

from src.core.config import Config

SYNC_REQUEST_TIMEOUT_SECONDS = 120
STREAM_REQUEST_TIMEOUT_SECONDS = 600


class LLMClient:
    def __init__(self):
        Config.load_env()
        self.providers = self._build_provider_chain()

    def _provider_from_env(self, *, route, base_url_key, api_key_key, model_key, default_base_url=None):
        base_url = Config.get(base_url_key, default_base_url)
        api_key = Config.get(api_key_key)
        model = Config.get(model_key)

        if not api_key and not model:
            return None
        if not api_key:
            raise ValueError(f"Missing environment variable: {api_key_key}")
        if not model:
            raise ValueError(f"Missing environment variable: {model_key}")
        if not base_url:
            raise ValueError(f"Missing environment variable: {base_url_key}")

        return {
            "route": route,
            "base_url": base_url.rstrip("/"),
            "model": model,
            "models": [model],
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
        return (
            int(major),
            int(minor or -1),
            int(patch or -1),
            0 if is_code_variant else 1,
        )

    def _normalize_parameter_name(self, name):
        return str(name).strip().lower().replace("-", "_")

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

    def _can_model_use_reasoning(self, provider, model):
        model_capabilities = provider.get("model_capabilities")
        if not isinstance(model_capabilities, dict):
            return True

        supported_parameters = model_capabilities.get(model)
        if supported_parameters is None:
            return True

        return self._supports_reasoning_parameter(supported_parameters)

    def _apply_model_capabilities_to_payload(self, payload, provider, model):
        if not isinstance(payload, dict) or "reasoning_effort" not in payload:
            return payload

        if self._can_model_use_reasoning(provider, model):
            return payload

        filtered_payload = dict(payload)
        filtered_payload.pop("reasoning_effort", None)
        logging.info(
            "Model %s does not advertise reasoning_effort support on route %s, omitting parameter",
            model,
            provider.get("route"),
        )
        return filtered_payload

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
        for index, item in enumerate(payload.get("data", [])):
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
                sort_key = (0, 0, 0, 0, index)
            else:
                # Preserve existing version-priority behavior for standard GPT-family ids.
                major, minor, patch, is_code_variant = version_key
                sort_key = (1, major, minor, patch, is_code_variant, index)

            candidates.append((sort_key, model_id, index, supported_parameters))

        # Keep latest/most specific versions first, then fall back to other aliases.
        candidates.sort(reverse=True)
        return [
            {
                "id": model_id,
                "supported_parameters": supported_parameters,
            }
            for _, model_id, _, supported_parameters in candidates
        ]

    def _build_provider_chain(self):
        providers = []

        primary = self._provider_from_env(
            route="cliproxyapi_primary",
            base_url_key="CLIPROXYAPI_BASE_URL",
            api_key_key="CLIPROXYAPI_API_KEY",
            model_key="CLIPROXYAPI_MODEL",
            default_base_url="http://127.0.0.1:8317/v1",
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

    def _describe_request_error(self, error):
        response = getattr(error, "response", None)
        if response is None:
            return str(error)

        details = ""
        try:
            details = response.text.strip()
        except Exception:
            details = ""

        if details:
            return f"{error} | body={details[:500]}"
        return str(error)

    def _is_model_compatibility_error(self, details):
        text = details.lower()
        return (
            "unknown provider for model" in text
            or "model is not supported" in text
            or "model not supported" in text
            or "unsupported" in text
        )

    def _ordered_providers(self, requested_model):
        requested_model = (requested_model or "").strip()
        if not requested_model:
            return self.providers

        prioritized = []
        fallback = []

        for provider in self.providers:
            models = [str(model) for model in (provider.get("models") or [provider.get("model")]) if model]
            if requested_model in models:
                provider_snapshot = dict(provider)
                provider_snapshot["models"] = [requested_model] + [model for model in models if model != requested_model]
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
                "model": provider["model"],
                "models": normalized_models,
                "base_url": provider["base_url"],
                "model_capabilities": model_capabilities,
            })

        return catalog

    def _post_with_failover(self, payload, stream=False, timeout=120, requested_model=None):
        provider_chain = self._ordered_providers(requested_model)
        errors = []

        for provider in provider_chain:
            url = provider["base_url"] + "/chat/completions"
            model_candidates = list(provider.get("models") or [provider["model"]])

            for index, model in enumerate(model_candidates):
                provider_payload = self._apply_model_capabilities_to_payload(
                    self._apply_model_settings(payload, model),
                    provider,
                    model,
                )

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
                    has_next_model = index + 1 < len(model_candidates)
                    if has_next_model and self._is_model_compatibility_error(details):
                        continue
                    break

        raise requests.RequestException("All LLM providers failed: " + " | ".join(errors))

    def chat(self, messages, stream=True, print_callback=None, model=None):
        """
        Send chat request to LLM.

        Args:
            messages: List of message dicts.
            stream: Whether to stream the response.
            print_callback: Function(tag, content) to handle stream output.
        """
        messages = copy.deepcopy(messages)

        reasoning_effort = Config.get("AI_REASONING_EFFORT") or "medium"
        payload = {
            "messages": messages,
            "stream": stream,
            "max_tokens": 4096,
            "temperature": float(Config.get("AI_TEMPERATURE", 0.6)),
            "top_p": 0.7,
            "frequency_penalty": 0.5,
            "n": 1,
        }
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort

        start_time = time.time()

        if stream:
            return self._handle_stream(
                payload,
                start_time,
                print_callback,
                reasoning_effort,
                model,
            )
        return self._handle_sync(payload, start_time, reasoning_effort, model)

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

    def _handle_sync(self, payload, start_time, reasoning_effort, model=None):
        response, used_model, used_route = self._post_with_failover(
            payload,
            stream=False,
            timeout=SYNC_REQUEST_TIMEOUT_SECONDS,
            requested_model=model,
        )
        data = response.json()

        message = data["choices"][0]["message"]
        usage = data.get("usage", {})
        duration = time.time() - start_time

        return {
            "content": self._extract_content(message),
            "thinking": message.get("reasoning_content") or "",
            "usage": usage,
            "duration": duration,
            "model": used_model,
            "provider_route": used_route,
            "reasoning_effort": reasoning_effort,
        }

    def _handle_stream(self, payload, start_time, print_callback, reasoning_effort, model=None):
        full_content = ""
        full_thinking = ""
        usage_data = {}

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
            )

            output("metadata", {
                "model": used_model,
                "provider_route": used_route,
                "reasoning_effort": reasoning_effort,
            })

            for line in response.iter_lines(chunk_size=1):
                if not line:
                    continue
                line_str = line.decode("utf-8")

                if line_str.startswith("data: "):
                    data_str = line_str[6:]
                    if data_str.strip() == "[DONE]":
                        if print_callback:
                            print_callback("done", "")
                        break

                    try:
                        data = json.loads(data_str)
                        if "usage" in data:
                            usage_data = data["usage"]

                        if "choices" in data and len(data["choices"]) > 0:
                            delta = data["choices"][0].get("delta", {})

                            reasoning = delta.get("reasoning_content", "")
                            if reasoning:
                                full_thinking += reasoning
                                output("thinking", reasoning)

                            content = delta.get("content", "")
                            if content:
                                full_content += content
                                output("content", content)
                    except json.JSONDecodeError:
                        continue

        except Exception as error:
            output("error", str(error))
            raise

        duration = time.time() - start_time

        return {
            "content": full_content,
            "thinking": full_thinking,
            "usage": {
                "prompt_tokens": usage_data.get("prompt_tokens", 0),
                "completion_tokens": usage_data.get("completion_tokens", 0),
                "total_tokens": usage_data.get("total_tokens", 0),
            },
            "duration": duration,
            "model": used_model,
            "provider_route": used_route,
            "reasoning_effort": reasoning_effort,
        }


# Backward-compatible alias for older imports.
SiliconFlowClient = LLMClient

import copy
import json
import logging
import re
import time

import requests

from src.core.config import Config


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
        match = re.match(r"^gpt-(\d+)(?:\.(\d+))?(?:\.(\d+))?$", model_id.lower())
        if not match:
            return None
        return tuple(int(part) if part is not None else -1 for part in match.groups())

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
            model_id = str(item.get("id", "")).strip()
            if not model_id:
                continue
            if "codex" in model_id.lower():
                continue
            version_key = self._model_version_key(model_id)
            if version_key is None:
                continue
            candidates.append((version_key, model_id))

        candidates.sort(reverse=True)
        return [model_id for _, model_id in candidates]

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
            primary["model"] = discovered_models[0]
            primary["models"] = discovered_models
            logging.info(
                "Auto-selected CLIProxyAPI primary model %s from candidates: %s",
                primary["model"],
                ", ".join(discovered_models),
            )
        else:
            logging.info(
                "CLIProxyAPI model discovery unavailable; using configured primary model %s",
                primary["model"],
            )
        providers.append(primary)

        secondary = self._provider_from_env(
            route="cliproxyapi_secondary",
            base_url_key="CLIPROXYAPI_SECONDARY_BASE_URL",
            api_key_key="CLIPROXYAPI_SECONDARY_API_KEY",
            model_key="CLIPROXYAPI_SECONDARY_MODEL",
            default_base_url="http://127.0.0.1:8045/v1",
        )
        if secondary:
            providers.append(secondary)

        fallback = self._provider_from_env(
            route="siliconflow_fallback",
            base_url_key="CLIPROXYAPI_FALLBACK_BASE_URL",
            api_key_key="CLIPROXYAPI_FALLBACK_API_KEY",
            model_key="CLIPROXYAPI_FALLBACK_MODEL",
            default_base_url="https://api.siliconflow.cn/v1",
        )
        if fallback:
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

    def _post_with_failover(self, payload, stream=False, timeout=120):
        errors = []

        for provider in self.providers:
            url = provider["base_url"] + "/chat/completions"
            model_candidates = list(provider.get("models") or [provider["model"]])

            for index, model in enumerate(model_candidates):
                provider_payload = self._apply_model_settings(payload, model)

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

    def chat(self, messages, stream=True, print_callback=None):
        """
        Send chat request to LLM.

        Args:
            messages: List of message dicts.
            stream: Whether to stream the response.
            print_callback: Function(tag, content) to handle stream output.
        """
        messages = copy.deepcopy(messages)

        if messages:
            last_msg = messages[-1]
            if last_msg.get("role") == "user":
                content = last_msg.get("content", "")
                messages[-1]["content"] = f"{content}\n\n{content}"

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
            return self._handle_stream(payload, start_time, print_callback, reasoning_effort)
        return self._handle_sync(payload, start_time, reasoning_effort)

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

    def _handle_sync(self, payload, start_time, reasoning_effort):
        response, used_model, used_route = self._post_with_failover(payload, stream=False, timeout=120)
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

    def _handle_stream(self, payload, start_time, print_callback, reasoning_effort):
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
            response, used_model, used_route = self._post_with_failover(payload, stream=True, timeout=300)

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

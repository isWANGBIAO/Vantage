import os
import requests
import json
import time
import logging
from src.core.config import Config

class SiliconFlowClient:
    def __init__(self):
        Config.load_env()
        self.base_url = Config.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
        self.model = Config.get("SILICONFLOW_MODEL")
        self.api_key = Config.get("SILICONFLOW_API_KEY")
        self.fallback_base_url = Config.get("SILICONFLOW_FALLBACK_BASE_URL", "https://api.siliconflow.cn/v1")
        self.fallback_model = Config.get("SILICONFLOW_FALLBACK_MODEL")
        self.fallback_api_key = Config.get("SILICONFLOW_FALLBACK_API_KEY")
        
        if not self.model:
            raise ValueError("Missing environment variable: SILICONFLOW_MODEL")
        if not self.api_key:
            raise ValueError("Missing environment variable: SILICONFLOW_API_KEY")

        self.headers = self._build_headers(self.api_key)
        self.fallback_headers = self._build_headers(self.fallback_api_key) if self._has_fallback() else None

    def _build_headers(self, api_key):
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _has_fallback(self):
        return bool(self.fallback_base_url and self.fallback_model and self.fallback_api_key)

    def _apply_model_settings(self, payload, model):
        updated = dict(payload)
        enable_thinking = "qwq" in model.lower() or "deepseek" in model.lower()
        updated["model"] = model
        updated["enable_thinking"] = enable_thinking
        updated["thinking_budget"] = 4096 if enable_thinking else 0
        return updated

    def _post_with_failover(self, payload, stream=False, timeout=120):
        primary_url = self.base_url.rstrip("/") + "/chat/completions"
        primary_payload = self._apply_model_settings(payload, self.model)

        try:
            response = requests.post(
                primary_url,
                json=primary_payload,
                headers=self.headers,
                timeout=timeout,
                stream=stream,
            )
            response.raise_for_status()
            return response, self.model, "primary"
        except requests.RequestException as primary_error:
            if not self._has_fallback():
                raise

            fallback_url = self.fallback_base_url.rstrip("/") + "/chat/completions"
            fallback_payload = self._apply_model_settings(payload, self.fallback_model)
            logging.warning(
                "Primary LLM failed (%s). Switching to fallback model %s at %s.",
                str(primary_error),
                self.fallback_model,
                self.fallback_base_url,
            )
            response = requests.post(
                fallback_url,
                json=fallback_payload,
                headers=self.fallback_headers,
                timeout=timeout,
                stream=stream,
            )
            response.raise_for_status()
            return response, self.fallback_model, "fallback"

    def chat(self, messages, stream=True, print_callback=None):
        """
        Send chat request to LLM.
        
        Args:
            messages: List of message dicts.
            stream: Whether to stream the response.
            print_callback: Function(tag, content) to handle stream output.
        """
        # [Auto-Repeat Prompt] - work on a copy to avoid mutating caller's data
        import copy
        messages = copy.deepcopy(messages)
        
        if messages and len(messages) > 0:
            last_msg = messages[-1]
            if last_msg.get("role") == "user":
                content = last_msg.get("content", "")
                messages[-1]["content"] = f"{content}\n\n{content}"

        payload = {
            "messages": messages,
            "stream": stream,
            "max_tokens": 4096,
            "min_p": 0.05,
            "stop": None,
            "temperature": float(Config.get("AI_TEMPERATURE", 0.6)),
            "top_p": 0.7,
            "top_k": 50,
            "frequency_penalty": 0.5,
            "n": 1,
            "response_format": {"type": "text"},
        }

        start_time = time.time()
        
        if stream:
            return self._handle_stream(payload, start_time, print_callback)
        else:
            return self._handle_sync(payload, start_time)

    def _handle_sync(self, payload, start_time):
        response, used_model, used_route = self._post_with_failover(payload, stream=False, timeout=120)
        data = response.json()
        
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        duration = time.time() - start_time
        
        return {
            "content": content,
            "thinking": "", 
            "usage": usage,
            "duration": duration,
            "model": used_model,
            "provider_route": used_route,
        }

    def _handle_stream(self, payload, start_time, print_callback):
        full_content = ""
        full_thinking = ""
        usage_data = {}
        
        def output(tag, content):
            if print_callback:
                print_callback(tag, content)
            else:
                 # Default output
                if tag == "thinking":
                    print(f"STREAM_THINKING:{json.dumps(content)}", flush=True)
                elif tag == "content":
                    print(f"STREAM_CONTENT:{json.dumps(content)}", flush=True)
                elif tag == "error":
                    print(f"STREAM_ERROR:{json.dumps(content)}", flush=True)

        try:
            response, used_model, used_route = self._post_with_failover(payload, stream=True, timeout=300)
            
            for line in response.iter_lines():
                if not line: continue
                line_str = line.decode('utf-8')
                
                if line_str.startswith("data: "):
                    data_str = line_str[6:]
                    if data_str.strip() == "[DONE]":
                        if print_callback: print_callback("done", "")
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
                        
        except Exception as e:
            output("error", str(e))
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
        }

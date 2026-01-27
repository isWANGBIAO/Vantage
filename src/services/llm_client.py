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
        
        if not self.model:
            raise ValueError("Missing environment variable: SILICONFLOW_MODEL")
        if not self.api_key:
            raise ValueError("Missing environment variable: SILICONFLOW_API_KEY")

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def chat(self, messages, stream=True, print_callback=None):
        """
        Send chat request to LLM.
        
        Args:
            messages: List of message dicts.
            stream: Whether to stream the response.
            print_callback: Function(tag, content) to handle stream output.
        """
        # [Auto-Repeat Prompt]
        # Identify the last message with role "user" and duplicate its content
        if messages and len(messages) > 0:
            last_msg = messages[-1]
            if last_msg.get("role") == "user":
                content = last_msg.get("content", "")
                # Avoid repeat on repeat (simple check if already repeated? - No, user wants it every time strictly, 
                # but we should be careful if it's already done by caller. 
                # The plan said we remove it from caller, so we can blindly do it here.)
                # However, to be safe against double application if script isn't updated perfectly or multiple calls:
                # But request is "Repeat twice prompt", usually means "Prompt \n\n Prompt".
                messages[-1]["content"] = f"{content}\n\n{content}"

        url = self.base_url.rstrip("/") + "/chat/completions"
        
        # Detect model capability (Thinking)
        enable_thinking = "qwq" in self.model.lower() or "deepseek" in self.model.lower()
        
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "max_tokens": 4096,
            "enable_thinking": enable_thinking,
            "thinking_budget": 4096 if enable_thinking else 0,
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
            return self._handle_stream(url, payload, start_time, print_callback)
        else:
            return self._handle_sync(url, payload, start_time)

    def _handle_sync(self, url, payload, start_time):
        response = requests.post(url, json=payload, headers=self.headers, timeout=120)
        response.raise_for_status()
        data = response.json()
        
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        duration = time.time() - start_time
        
        return {
            "content": content,
            "thinking": "", 
            "usage": usage,
            "duration": duration
        }

    def _handle_stream(self, url, payload, start_time, print_callback):
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
            response = requests.post(url, json=payload, headers=self.headers, timeout=300, stream=True)
            response.raise_for_status()
            
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
            "duration": duration
        }

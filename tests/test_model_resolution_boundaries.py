"""Real loopback providers exercise catalog, routing and profile resolution."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend import chat, providers, settings
from src.core import user_config
from src.core.config import Config
from src.services.llm_client import LLMClient


@pytest.fixture
def provider_runtime(monkeypatch, tmp_path):
    for name in ("DATA", "CONFIG", "HISTORY", "LOG", "PLOT", "CACHE", "RUNTIME", "MIGRATION"):
        monkeypatch.setenv(f"VANTAGE_{name}_DIR", str(tmp_path / name.lower()))
    monkeypatch.setenv("VANTAGE_APP_MODE", "development")
    monkeypatch.setenv("VANTAGE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("AI_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("AI_HEALTH_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(Config, "load_env", lambda: None)
    observed = []
    behavior = {"fail_secondary": False}

    class Provider(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(503 if self.path.startswith("/broken") else 200)
            body = json.dumps([] if self.path.startswith("/malformed") else {"data": None} if self.path.startswith("/wrong-data") else {"data": []}).encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            observed.append((self.path, payload))
            if behavior["fail_secondary"] and self.path.startswith("/secondary"):
                body = b'{"error":{"message":"synthetic model not supported"}}'
                self.send_response(400)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if payload.get("stream"):
                body = b'data: {"choices":[{"delta":{"content":"synthetic success"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            else:
                body = json.dumps({"choices": [{"message": {"content": "synthetic success"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = f"http://127.0.0.1:{server.server_port}"

    def configure(entries, **extra):
        config = {"selected_provider": "primary", "providers": {}}
        for route, model in entries:
            config["providers"][route] = {
                "base_url": f"{root}/{route}/v1", "api_key": "synthetic-only-key",
                "model": model, "models": [model] if model else [],
            }
        config.update(extra)
        user_config.save_provider_config(config)

    configure.behavior = behavior
    yield configure, observed
    server.shutdown()
    server.server_close()
    thread.join(5)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("broken_route", ["broken", "malformed", "wrong-data"])
def test_unresolved_backup_does_not_disable_healthy_default_or_catalog(provider_runtime, stream, broken_route):
    configure, observed = provider_runtime
    configure([("primary", "healthy-model"), (broken_route, "")])
    app = FastAPI()
    app.include_router(providers.router)
    with TestClient(app) as api:
        catalog = api.get("/api/v1/models").json()
    assert catalog["models"] == ["healthy-model"]
    client = LLMClient()
    assert broken_route in client.provider_errors
    result = client.chat([{"role": "user", "content": "synthetic"}], stream=stream, provider_route="primary")
    assert result["content"] == "synthetic success"
    assert len(observed) == 1
    assert observed[0][1]["model"] == "healthy-model"


def test_all_unresolved_candidates_still_fail_explicitly(provider_runtime):
    configure, _ = provider_runtime
    configure([("broken", "")])
    with pytest.raises(ValueError):
        LLMClient()


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("requested", ["target-model", "Pro/target-model"])
def test_model_only_override_selects_matching_provider_before_default(provider_runtime, stream, requested):
    configure, observed = provider_runtime
    configure([("primary", "default-model"), ("secondary", "Pro/target-model")])
    result = LLMClient().chat([{"role": "user", "content": "synthetic"}], model=requested, stream=stream)
    assert len(observed) == 1
    assert observed[0][0] == "/secondary/v1/chat/completions"
    assert observed[0][1]["model"] == "Pro/target-model"
    assert result["provider_route"] == "secondary"
    assert result["requested_provider_route"] == "secondary"
    assert result["fallback_used"] is False


def test_http_chat_model_only_uses_matching_route_in_real_run_prompt_child(provider_runtime):
    configure, observed = provider_runtime
    configure([("primary", "default-model"), ("secondary", "target-model")])
    app = FastAPI()
    app.include_router(chat.router)
    app.include_router(settings.router)
    with TestClient(app) as api:
        response = api.post("/api/v1/chat", json={"message": "synthetic", "model": "target-model"})
    assert response.status_code == 200
    assert len(observed) == 1
    assert observed[0][0] == "/secondary/v1/chat/completions"
    assert observed[0][1]["model"] == "target-model"
    assert any(json.loads(line).get("done") for line in response.text.splitlines())


@pytest.mark.parametrize("stream", [False, True])
def test_model_only_fallback_is_recorded_only_after_the_target_is_attempted(provider_runtime, stream):
    configure, observed = provider_runtime
    configure([("primary", "default-model"), ("secondary", "target-model")])
    configure.behavior["fail_secondary"] = True
    result = LLMClient().chat([{"role": "user", "content": "synthetic"}], model="target-model", stream=stream)
    assert [call[0] for call in observed] == ["/secondary/v1/chat/completions", "/primary/v1/chat/completions"]
    assert result["requested_provider_route"] == "secondary"
    assert result["provider_route"] == "primary"
    assert result["fallback_used"] is True


def test_exact_profile_wins_over_earlier_builtin_wildcard(provider_runtime):
    configure, observed = provider_runtime
    configure([("primary", "Qwen3.8-27B")], model_profiles={
        "qwen3.8-27b": {"parameters": {"temperature": 0.25, "top_k": 7}, "reasoning_tiers": ["low", "high"], "reasoning_aliases": {"xhigh": "high"}},
    })
    app = FastAPI()
    app.include_router(providers.router)
    with TestClient(app) as api:
        catalog = api.get("/api/v1/models").json()
    assert catalog["model_options"][0]["reasoning_tiers"] == ["low", "high"]
    LLMClient().chat([{"role": "user", "content": "synthetic"}], stream=False, reasoning_effort="xhigh")
    assert observed[0][1]["temperature"] == 0.25
    assert observed[0][1]["top_k"] == 7
    assert observed[0][1]["reasoning_effort"] == "high"


def test_more_specific_wildcard_profile_wins_over_builtin_family(provider_runtime):
    configure, observed = provider_runtime
    configure([("primary", "Qwen3.8-27B")], model_profiles={"qwen3.8-27*": {"parameters": {"temperature": 0.35}}})
    LLMClient().chat([{"role": "user", "content": "synthetic"}], stream=False)
    assert observed[0][1]["temperature"] == 0.35


@pytest.mark.parametrize("model,omitted", [("zai-org/GLM-5.3-Flash", "max_tokens"), ("Qwen3.8-27B", "top_k")])
def test_intentionally_omitted_profile_parameters_do_not_crash_logging(provider_runtime, model, omitted):
    configure, observed = provider_runtime
    pattern = "glm-5.3-flash*" if "GLM" in model else "qwen3.8-*"
    configure([("primary", model)], model_profiles={pattern: {"omit_parameters": [omitted]}})
    client = LLMClient()
    client.chat([{"role": "user", "content": "synthetic"}], stream=False)
    assert omitted not in observed[0][1]

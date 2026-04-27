import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from src.services import llm_client


class LLMClientTests(unittest.TestCase):
    def setUp(self):
        self._provider_chain_patch = patch.object(
            llm_client.user_config,
            "get_provider_chain_config",
            return_value=[],
            create=True,
        )
        self._provider_chain_patch.start()

    def tearDown(self):
        self._provider_chain_patch.stop()

    def _env(self):
        return {
            "CLIPROXYAPI_BASE_URL": "http://127.0.0.1:8317/v1",
            "CLIPROXYAPI_API_KEY": "unit-test-key",
            "CLIPROXYAPI_MODEL": "gpt-5.1",
            "CLIPROXYAPI_SECONDARY_BASE_URL": "http://127.0.0.1:8045/v1",
            "CLIPROXYAPI_SECONDARY_API_KEY": "secondary-key",
            "CLIPROXYAPI_SECONDARY_MODEL": "gemini-3.1-pro-high",
            "CLIPROXYAPI_FALLBACK_BASE_URL": "https://api.siliconflow.cn/v1",
            "CLIPROXYAPI_FALLBACK_API_KEY": "fallback-key",
            "CLIPROXYAPI_FALLBACK_MODEL": "Pro/deepseek-ai/DeepSeek-V3.2",
            "AI_TEMPERATURE": "0.6",
        }

    def _models_response(self, model_ids):
        response = Mock()
        response.raise_for_status.return_value = None
        models = []
        for model_id in model_ids:
            if isinstance(model_id, dict):
                models.append(model_id)
            else:
                models.append({"id": model_id})
        response.json.return_value = {"data": models}
        return response

    def _make_client(self, discovered_models=None, discovery_error=None):
        client_cls = getattr(llm_client, "LLMClient", None)
        self.assertIsNotNone(client_cls, "LLMClient should be exported from src.services.llm_client")
        if discovery_error is not None:
            get_patch = patch.object(llm_client.requests, "get", side_effect=discovery_error)
        else:
            if discovered_models is None:
                discovered_models = ["gpt-5.2", "gpt-5.2-codex", "gpt-5.1", "gpt-5"]
            get_patch = patch.object(
                llm_client.requests,
                "get",
                return_value=self._models_response(discovered_models),
            )

        with (
            patch.object(llm_client.Config, "load_env", return_value=None),
            patch.dict(os.environ, self._env(), clear=True),
            patch.object(llm_client.user_config, "get_provider_chain_config", return_value=[], create=True),
            patch.object(llm_client.user_config, "get_active_provider_config", return_value=None),
            get_patch,
        ):
            return client_cls()

    def test_primary_provider_auto_selects_latest_non_codex_model(self):
        client = self._make_client(
            discovered_models=["gpt-5.1-codex", "gpt-5", "gpt-5.2", "gpt-5.1", "gpt-5.2-codex"],
        )

        self.assertEqual(client.providers[0]["model"], "gpt-5.2")

    def test_primary_provider_prefers_base_model_over_mini_variant_for_same_version(self):
        client = self._make_client(
            discovered_models=["gpt-5.2", "gpt-5.3-codex-spark", "gpt-5.4", "gpt-5.4-mini"],
        )

        self.assertEqual(client.providers[0]["model"], "gpt-5.4")
        self.assertEqual(
            client.providers[0]["models"][:3],
            ["gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex-spark"],
        )

    def test_primary_provider_uses_configured_model_when_discovery_fails(self):
        client = self._make_client(discovery_error=llm_client.requests.RequestException("discovery failed"))

        self.assertEqual(client.providers[0]["model"], "gpt-5.1")

    def test_builds_provider_chain_from_cliproxyapi_config(self):
        client = self._make_client()
        providers = getattr(client, "providers", None)

        self.assertIsNotNone(providers, "LLMClient should expose ordered providers")
        self.assertEqual(
            [provider["route"] for provider in providers],
            ["cliproxyapi_primary", "cliproxyapi_secondary", "siliconflow_fallback"],
        )
        self.assertEqual(
            [provider["base_url"] for provider in providers],
            [
                "http://127.0.0.1:8317/v1",
                "http://127.0.0.1:8045/v1",
                "https://api.siliconflow.cn/v1",
            ],
        )
        self.assertEqual(
            [provider["model"] for provider in providers],
            ["gpt-5.2", "gemini-3.1-pro-high", "Pro/deepseek-ai/DeepSeek-V3.2"],
        )
        self.assertEqual(providers[0]["models"], ["gpt-5.2", "gpt-5.2-codex", "gpt-5.1", "gpt-5"])

    def test_user_provider_config_overrides_environment_chain_without_exposing_key(self):
        user_provider = {
            "route": "cliproxyapi",
            "base_url": "https://user-config.invalid/v1",
            "api_key": "sk-user-secret",
            "model": "gpt-5.4",
        }

        with (
            patch.object(llm_client.Config, "load_env", return_value=None),
            patch.dict(os.environ, self._env(), clear=True),
            patch.object(llm_client.user_config, "get_provider_chain_config", return_value=[user_provider], create=True),
            patch.object(llm_client.user_config, "get_active_provider_config", return_value=user_provider),
            patch.object(llm_client.requests, "get", return_value=self._models_response(["gpt-5.4"])),
        ):
            client = llm_client.LLMClient()

        self.assertEqual(len(client.providers), 1)
        self.assertEqual(client.providers[0]["route"], "cliproxyapi")
        self.assertEqual(client.providers[0]["base_url"], "https://user-config.invalid/v1")
        self.assertEqual(client.providers[0]["headers"]["Authorization"], "Bearer sk-user-secret")
        catalog = client.get_model_catalog()
        self.assertNotIn("api_key", catalog[0])
        self.assertNotIn("headers", catalog[0])

    def test_user_provider_chain_uses_all_enabled_providers_without_environment_chain(self):
        user_providers = [
            {
                "route": "local",
                "name": "Local Proxy",
                "type": "openai-compatible",
                "base_url": "http://127.0.0.1:8317/v1",
                "api_key": "sk-local",
                "model": "gpt-5.5",
                "models": ["gpt-5.5", "gpt-5.4"],
            },
            {
                "route": "cloud",
                "name": "Cloud Proxy",
                "type": "openai-compatible",
                "base_url": "https://cloud.invalid/v1",
                "api_key": "sk-cloud",
                "model": "gpt-5.4",
                "models": ["gpt-5.4"],
            },
        ]

        with (
            patch.object(llm_client.Config, "load_env", return_value=None),
            patch.dict(os.environ, self._env(), clear=True),
            patch.object(llm_client.user_config, "get_provider_chain_config", return_value=user_providers, create=True),
            patch.object(llm_client.user_config, "get_active_provider_config", return_value=user_providers[0]),
            patch.object(llm_client.requests, "get", return_value=self._models_response(["gpt-5.5", "gpt-5.4"])),
        ):
            client = llm_client.LLMClient()

        self.assertEqual([provider["route"] for provider in client.providers], ["local", "cloud"])
        self.assertEqual(client.providers[0]["models"][:2], ["gpt-5.5", "gpt-5.4"])
        self.assertEqual(client.providers[1]["model"], "gpt-5.4")

    def test_ordered_providers_prioritizes_requested_provider_route_when_models_overlap(self):
        client = self._make_client()
        client.providers = [
            {
                "route": "local",
                "base_url": "http://127.0.0.1:8317/v1",
                "model": "gpt-5.5",
                "models": ["gpt-5.5"],
                "headers": {},
            },
            {
                "route": "cloud",
                "base_url": "https://cloud.invalid/v1",
                "model": "gpt-5.5",
                "models": ["gpt-5.5"],
                "headers": {},
            },
        ]

        ordered = client._ordered_providers(
            requested_model="gpt-5.5",
            requested_provider_route="cloud",
        )

        self.assertEqual([provider["route"] for provider in ordered], ["cloud", "local"])

    def test_fallback_provider_uses_own_model_after_requested_provider_fails(self):
        client = self._make_client()
        client.providers = [
            {
                "route": "custom",
                "base_url": "http://127.0.0.1:8317/v1",
                "model": "gpt-5.5",
                "models": ["gpt-5.5"],
                "headers": {},
            },
            {
                "route": "SJTU",
                "base_url": "https://models.sjtu.edu.cn/api/v1",
                "model": "qwen3vl",
                "models": ["qwen3vl", "deepseek-chat"],
                "headers": {},
            },
        ]
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None

        with patch.object(
            llm_client.requests,
            "post",
            side_effect=[llm_client.requests.HTTPError("temporary custom failure"), fake_response],
        ) as mock_post:
            response, used_model, used_route = client._post_with_failover(
                {"messages": [{"role": "user", "content": "ping"}]},
                stream=False,
                timeout=12,
                requested_model="gpt-5.5",
                requested_provider_route="custom",
            )

        self.assertIs(response, fake_response)
        self.assertEqual(used_model, "qwen3vl")
        self.assertEqual(used_route, "SJTU")
        self.assertEqual(
            [call.kwargs["json"]["model"] for call in mock_post.call_args_list],
            ["gpt-5.5", "qwen3vl"],
        )

    def test_retries_local_custom_provider_after_startup_connection_refused(self):
        client = self._make_client()
        client.providers = [
            {
                "route": "custom",
                "base_url": "http://127.0.0.1:8317/v1",
                "model": "gpt-5.5",
                "models": ["gpt-5.5"],
                "headers": {},
            },
            {
                "route": "SJTU",
                "base_url": "https://models.sjtu.edu.cn/api/v1",
                "model": "qwen3vl",
                "models": ["qwen3vl"],
                "headers": {},
            },
        ]
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None

        connection_error = llm_client.requests.ConnectionError(
            "Failed to establish a new connection: [WinError 10061] connection refused"
        )

        with (
            patch.object(
                llm_client.requests,
                "post",
                side_effect=[connection_error, fake_response],
            ) as mock_post,
            patch.object(llm_client.time, "sleep", return_value=None) as mock_sleep,
        ):
            response, used_model, used_route = client._post_with_failover(
                {"messages": [{"role": "user", "content": "ping"}]},
                stream=False,
                timeout=12,
                requested_model="gpt-5.5",
                requested_provider_route="custom",
            )

        self.assertIs(response, fake_response)
        self.assertEqual(used_model, "gpt-5.5")
        self.assertEqual(used_route, "custom")
        self.assertEqual(
            [call.args[0] for call in mock_post.call_args_list],
            [
                "http://127.0.0.1:8317/v1/chat/completions",
                "http://127.0.0.1:8317/v1/chat/completions",
            ],
        )
        mock_sleep.assert_called_once()

    def test_retries_next_primary_model_after_model_error(self):
        client = self._make_client(discovered_models=["gpt-5.2", "gpt-5.1", "gpt-5"])
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None

        model_error = llm_client.requests.HTTPError("model rejected")
        model_error.response = Mock()
        model_error.response.text = '{"error":{"message":"unknown provider for model"}}'

        with patch.object(
            llm_client.requests,
            "post",
            side_effect=[model_error, fake_response],
        ) as mock_post:
            response, used_model, used_route = client._post_with_failover(
                {"messages": [{"role": "user", "content": "ping"}]},
                stream=False,
                timeout=12,
            )

        self.assertIs(response, fake_response)
        self.assertEqual(used_model, "gpt-5.1")
        self.assertEqual(used_route, "cliproxyapi_primary")
        self.assertEqual(
            [call.kwargs["json"]["model"] for call in mock_post.call_args_list],
            ["gpt-5.2", "gpt-5.1"],
        )

    def test_code_variant_models_are_detected(self):
        client = self._make_client(
            discovered_models=["gpt-5.3", "gpt-5.3-code-x", "gpt-5.2-codex", "gpt-5.2", "gpt-5.1-code"],
        )

        self.assertEqual(client.providers[0]["model"], "gpt-5.3")
        self.assertEqual(
            client.providers[0]["models"][:2],
            ["gpt-5.3", "gpt-5.3-code-x"],
        )
        self.assertIn("gpt-5.2", client.providers[0]["models"])
        self.assertIn("gpt-5.2-codex", client.providers[0]["models"])
        self.assertIn("gpt-5.1-code", client.providers[0]["models"])

    def test_retries_secondary_provider_after_primary_failure(self):
        client = self._make_client()
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None

        with patch.object(
            llm_client.requests,
            "post",
            side_effect=[llm_client.requests.RequestException("primary failed"), fake_response],
        ) as mock_post:
            response, used_model, used_route = client._post_with_failover(
                {"messages": [{"role": "user", "content": "ping"}]},
                stream=False,
                timeout=12,
            )

        self.assertIs(response, fake_response)
        self.assertEqual(used_model, "gemini-3.1-pro-high")
        self.assertEqual(used_route, "cliproxyapi_secondary")
        self.assertEqual(
            [call.args[0] for call in mock_post.call_args_list],
            [
                "http://127.0.0.1:8317/v1/chat/completions",
                "http://127.0.0.1:8045/v1/chat/completions",
            ],
        )

    def test_retries_same_primary_model_after_five_extra_transient_eof_attempts(self):
        client = self._make_client(discovered_models=["gpt-5.4", "gpt-5.4-mini"])
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None

        transient_error = llm_client.requests.HTTPError("upstream eof")
        transient_error.response = Mock()
        transient_error.response.status_code = 500
        transient_error.response.text = '{"error":{"message":"unexpected EOF","type":"server_error","code":"internal_server_error"}}'

        with patch.object(
            llm_client.requests,
            "post",
            side_effect=[
                transient_error,
                transient_error,
                transient_error,
                transient_error,
                transient_error,
                fake_response,
            ],
        ) as mock_post:
            response, used_model, used_route = client._post_with_failover(
                {"messages": [{"role": "user", "content": "ping"}]},
                stream=False,
                timeout=12,
            )

        self.assertIs(response, fake_response)
        self.assertEqual(used_model, "gpt-5.4")
        self.assertEqual(used_route, "cliproxyapi_primary")
        self.assertEqual(
            [call.args[0] for call in mock_post.call_args_list],
            [
                "http://127.0.0.1:8317/v1/chat/completions",
                "http://127.0.0.1:8317/v1/chat/completions",
                "http://127.0.0.1:8317/v1/chat/completions",
                "http://127.0.0.1:8317/v1/chat/completions",
                "http://127.0.0.1:8317/v1/chat/completions",
                "http://127.0.0.1:8317/v1/chat/completions",
            ],
        )
        self.assertEqual(
            [call.kwargs["json"]["model"] for call in mock_post.call_args_list],
            ["gpt-5.4", "gpt-5.4", "gpt-5.4", "gpt-5.4", "gpt-5.4", "gpt-5.4"],
        )

    def test_chat_includes_reasoning_effort_when_configured(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "choices": [{"message": {"content": "done"}}],
            "usage": {},
        }

        with (
            patch.object(llm_client.Config, "load_env", return_value=None),
            patch.object(llm_client.user_config, "get_active_provider_config", return_value=None),
            patch.dict(
                os.environ,
                {
                    **self._env(),
                    "AI_REASONING_EFFORT": "xhigh",
                },
                clear=True,
            ),
            patch.object(
                llm_client.requests,
                "get",
                return_value=self._models_response(["gpt-5.2", "gpt-5.1", "gpt-5"]),
            ),
            patch.object(llm_client.requests, "post", return_value=fake_response) as mock_post,
        ):
            client = llm_client.LLMClient()
            client.chat([{"role": "user", "content": "ping"}], stream=False)

        self.assertEqual(mock_post.call_args.kwargs["json"]["reasoning_effort"], "xhigh")

    def test_chat_omits_reasoning_effort_when_model_lacks_support(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "choices": [{"message": {"content": "done"}}],
            "usage": {},
        }
        models = [
            {"id": "gpt-5.2", "supported_parameters": ["reasoning_effort", "max_tokens"]},
            {"id": "gpt-5.1", "supported_parameters": ["max_tokens", "temperature"]},
        ]

        with (
            patch.object(llm_client.Config, "load_env", return_value=None),
            patch.object(llm_client.user_config, "get_active_provider_config", return_value=None),
            patch.dict(
                os.environ,
                {
                    **self._env(),
                    "AI_REASONING_EFFORT": "xhigh",
                },
                clear=True,
            ),
            patch.object(
                llm_client.requests,
                "get",
                return_value=self._models_response(models),
            ),
            patch.object(
                llm_client.requests,
                "post",
                return_value=fake_response,
            ) as mock_post,
        ):
            client = llm_client.LLMClient()
            result_payload = client._post_with_failover(
                {"model": "gpt-5.1", "reasoning_effort": "xhigh", "messages": [{"role": "user", "content": "ping"}]},
                stream=False,
                timeout=12,
                requested_model="gpt-5.1",
            )

            used_request = mock_post.call_args.kwargs["json"]
            self.assertNotIn("reasoning_effort", used_request)
            self.assertEqual(result_payload[1], "gpt-5.1")

    def test_chat_includes_reasoning_effort_when_model_supports_it(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "choices": [{"message": {"content": "done"}}],
            "usage": {},
        }
        models = [
            {"id": "gpt-5.2", "supported_parameters": ["reasoning_effort", "max_tokens"]},
            {"id": "gpt-5.1", "supported_parameters": ["max_tokens", "temperature"]},
        ]

        with (
            patch.object(llm_client.Config, "load_env", return_value=None),
            patch.object(llm_client.user_config, "get_active_provider_config", return_value=None),
            patch.dict(
                os.environ,
                {
                    **self._env(),
                    "AI_REASONING_EFFORT": "xhigh",
                },
                clear=True,
            ),
            patch.object(
                llm_client.requests,
                "get",
                return_value=self._models_response(models),
            ),
            patch.object(
                llm_client.requests,
                "post",
                return_value=fake_response,
            ) as mock_post,
        ):
            client = llm_client.LLMClient()
            result_payload = client._post_with_failover(
                {"model": "gpt-5.2", "reasoning_effort": "xhigh", "messages": [{"role": "user", "content": "ping"}]},
                stream=False,
                timeout=12,
                requested_model="gpt-5.2",
            )

            used_request = mock_post.call_args.kwargs["json"]
            self.assertEqual(used_request["reasoning_effort"], "xhigh")
            self.assertEqual(result_payload[1], "gpt-5.2")

    def test_chat_maps_siliconflow_deepseek_reasoning_effort_to_thinking_controls(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "choices": [{"message": {"content": "done", "reasoning_content": "thought"}}],
            "usage": {},
        }

        with (
            patch.object(llm_client.Config, "load_env", return_value=None),
            patch.object(llm_client.user_config, "get_active_provider_config", return_value=None),
            patch.dict(
                os.environ,
                {
                    **self._env(),
                    "AI_REASONING_EFFORT": "xhigh",
                },
                clear=True,
            ),
            patch.object(
                llm_client.requests,
                "get",
                return_value=self._models_response(["gpt-5.2", "gpt-5.1", "gpt-5"]),
            ),
            patch.object(
                llm_client.requests,
                "post",
                return_value=fake_response,
            ) as mock_post,
        ):
            client = llm_client.LLMClient()
            response, used_model, used_route = client._post_with_failover(
                {
                    "model": "Pro/deepseek-ai/DeepSeek-V3.2",
                    "reasoning_effort": "xhigh",
                    "messages": [{"role": "user", "content": "ping"}],
                },
                stream=False,
                timeout=12,
                requested_model="Pro/deepseek-ai/DeepSeek-V3.2",
            )

        self.assertIs(response, fake_response)
        self.assertEqual(used_model, "Pro/deepseek-ai/DeepSeek-V3.2")
        self.assertEqual(used_route, "siliconflow_fallback")
        used_request = mock_post.call_args.kwargs["json"]
        self.assertTrue(used_request["enable_thinking"])
        self.assertEqual(used_request["thinking_budget"], 8192)
        self.assertNotIn("reasoning_effort", used_request)

    def test_chat_maps_siliconflow_deepseek_medium_reasoning_effort_to_2048_budget(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "choices": [{"message": {"content": "done"}}],
            "usage": {},
        }

        with (
            patch.object(llm_client.Config, "load_env", return_value=None),
            patch.object(llm_client.user_config, "get_active_provider_config", return_value=None),
            patch.dict(
                os.environ,
                {
                    **self._env(),
                    "AI_REASONING_EFFORT": "medium",
                },
                clear=True,
            ),
            patch.object(
                llm_client.requests,
                "get",
                return_value=self._models_response(["gpt-5.2", "gpt-5.1", "gpt-5"]),
            ),
            patch.object(
                llm_client.requests,
                "post",
                return_value=fake_response,
            ) as mock_post,
        ):
            client = llm_client.LLMClient()
            client._post_with_failover(
                {
                    "model": "deepseek-ai/DeepSeek-V3.2",
                    "reasoning_effort": "medium",
                    "messages": [{"role": "user", "content": "ping"}],
                },
                stream=False,
                timeout=12,
                requested_model="deepseek-ai/DeepSeek-V3.2",
            )

        used_request = mock_post.call_args.kwargs["json"]
        self.assertEqual(used_request["thinking_budget"], 2048)
        self.assertTrue(used_request["enable_thinking"])
        self.assertNotIn("reasoning_effort", used_request)

    def test_chat_defaults_reasoning_effort_to_medium(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "choices": [{"message": {"content": "done"}}],
            "usage": {},
        }

        env = self._env()
        env.pop("AI_REASONING_EFFORT", None)

        with (
            patch.object(llm_client.Config, "load_env", return_value=None),
            patch.object(llm_client.user_config, "get_active_provider_config", return_value=None),
            patch.dict(os.environ, env, clear=True),
            patch.object(
                llm_client.requests,
                "get",
                return_value=self._models_response(["gpt-5.2", "gpt-5.1", "gpt-5"]),
            ),
            patch.object(llm_client.requests, "post", return_value=fake_response) as mock_post,
        ):
            client = llm_client.LLMClient()
            client.chat([{"role": "user", "content": "ping"}], stream=False)

        self.assertEqual(mock_post.call_args.kwargs["json"]["reasoning_effort"], "medium")

    def test_streaming_chat_uses_small_iter_lines_chunk_size(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.iter_lines.return_value = [
            b'data: {"choices":[{"delta":{"content":"A"}}]}',
            b'data: [DONE]',
        ]

        with (
            patch.object(llm_client.Config, "load_env", return_value=None),
            patch.object(llm_client.user_config, "get_active_provider_config", return_value=None),
            patch.dict(os.environ, self._env(), clear=True),
            patch.object(
                llm_client.requests,
                "get",
                return_value=self._models_response(["gpt-5.2", "gpt-5.1", "gpt-5"]),
            ),
            patch.object(llm_client.requests, "post", return_value=fake_response),
        ):
            client = llm_client.LLMClient()
            result = client.chat(
                [{"role": "user", "content": "ping"}],
                stream=True,
                print_callback=lambda *_: None,
            )

        self.assertEqual(result["content"], "A")
        fake_response.iter_lines.assert_called_once_with(chunk_size=1)

    def test_streaming_chat_uses_ten_minute_read_timeout(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.iter_lines.return_value = [
            b'data: {"choices":[{"delta":{"content":"A"}}]}',
            b'data: [DONE]',
        ]

        with (
            patch.object(llm_client.Config, "load_env", return_value=None),
            patch.object(llm_client.user_config, "get_active_provider_config", return_value=None),
            patch.dict(os.environ, self._env(), clear=True),
            patch.object(
                llm_client.requests,
                "get",
                return_value=self._models_response(["gpt-5.2", "gpt-5.1", "gpt-5"]),
            ),
            patch.object(llm_client.requests, "post", return_value=fake_response) as mock_post,
        ):
            client = llm_client.LLMClient()
            client.chat(
                [{"role": "user", "content": "ping"}],
                stream=True,
                print_callback=lambda *_: None,
            )

        self.assertEqual(mock_post.call_args.kwargs["timeout"], 600)

    def test_streaming_chat_emits_selected_model_metadata_before_content(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.iter_lines.return_value = [
            b'data: {"choices":[{"delta":{"content":"A"}}]}',
            b'data: [DONE]',
        ]
        events = []

        def capture_event(tag, content):
            events.append((tag, content))

        with (
            patch.object(llm_client.Config, "load_env", return_value=None),
            patch.object(llm_client.user_config, "get_active_provider_config", return_value=None),
            patch.dict(os.environ, self._env(), clear=True),
            patch.object(
                llm_client.requests,
                "get",
                return_value=self._models_response(["gpt-5.2", "gpt-5.1", "gpt-5"]),
            ),
            patch.object(
                llm_client.requests,
                "post",
                side_effect=[llm_client.requests.RequestException("primary failed"), fake_response],
            ),
        ):
            client = llm_client.LLMClient()
            result = client.chat(
                [{"role": "user", "content": "ping"}],
                stream=True,
                print_callback=capture_event,
            )

        self.assertEqual(result["model"], "gemini-3.1-pro-high")
        self.assertEqual(result["provider_route"], "cliproxyapi_secondary")
        self.assertGreaterEqual(len(events), 3)
        self.assertEqual(
            events[0],
            (
                "metadata",
                {
                    "model": "gemini-3.1-pro-high",
                    "provider_route": "cliproxyapi_secondary",
                    "requested_model": "gpt-5.2",
                    "requested_provider_route": "cliproxyapi_primary",
                    "fallback_used": True,
                    "reasoning_effort": "medium",
                },
            ),
        )
        self.assertEqual(events[1], ("content", "A"))
        self.assertEqual(events[2], ("done", ""))

    def test_streaming_chat_without_callback_does_not_print_metadata_event(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.iter_lines.return_value = [
            b'data: {"choices":[{"delta":{"content":"A"}}]}',
            b'data: [DONE]',
        ]
        stdout = io.StringIO()

        with (
            patch.object(llm_client.Config, "load_env", return_value=None),
            patch.object(llm_client.user_config, "get_active_provider_config", return_value=None),
            patch.dict(os.environ, self._env(), clear=True),
            patch.object(
                llm_client.requests,
                "get",
                return_value=self._models_response(["gpt-5.2", "gpt-5.1", "gpt-5"]),
            ),
            patch.object(llm_client.requests, "post", return_value=fake_response),
            redirect_stdout(stdout),
        ):
            client = llm_client.LLMClient()
            client.chat(
                [{"role": "user", "content": "ping"}],
                stream=True,
                print_callback=None,
            )

        output = stdout.getvalue()
        self.assertIn('STREAM_CONTENT:"A"', output)
        self.assertNotIn("STREAM_METADATA:", output)

    def test_sync_chat_records_completed_call_with_session_recorder(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "choices": [{"message": {"content": "done"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
        }
        recorder = Mock()

        with (
            patch.object(llm_client.Config, "load_env", return_value=None),
            patch.object(llm_client.user_config, "get_active_provider_config", return_value=None),
            patch.dict(os.environ, self._env(), clear=True),
            patch.object(
                llm_client.requests,
                "get",
                return_value=self._models_response(["gpt-5.2", "gpt-5.1", "gpt-5"]),
            ),
            patch.object(llm_client.requests, "post", return_value=fake_response),
            patch.object(llm_client, "SessionRecorder", return_value=recorder),
        ):
            client = llm_client.LLMClient()
            result = client.chat(
                [{"role": "user", "content": "ping"}],
                stream=False,
                source="chat",
                entrypoint="src/scripts/run_prompt.py",
            )

        self.assertEqual(result["content"], "done")
        recorder.record_request_started.assert_called_once()
        recorder.record_message_snapshot.assert_called_once()
        recorder.record_request_completed.assert_called_once()
        recorder.record_token_count.assert_called_once()
        completed_kwargs = recorder.record_request_completed.call_args.kwargs
        self.assertEqual(completed_kwargs["usage"]["total_tokens"], 16)
        self.assertEqual(completed_kwargs["model"], "gpt-5.2")
        self.assertEqual(completed_kwargs["provider_route"], "cliproxyapi_primary")
        self.assertIsNone(completed_kwargs["first_token_latency"])
        self.assertIsNone(result["first_token_latency"])

    def test_streaming_chat_records_completed_call_with_session_recorder(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.iter_lines.return_value = [
            b'data: {"choices":[{"delta":{"content":"A"}}]}',
            b'data: {"usage":{"prompt_tokens":8,"completion_tokens":2,"total_tokens":10}}',
            b'data: [DONE]',
        ]
        recorder = Mock()

        with (
            patch.object(llm_client.Config, "load_env", return_value=None),
            patch.object(llm_client.user_config, "get_active_provider_config", return_value=None),
            patch.dict(os.environ, self._env(), clear=True),
            patch.object(
                llm_client.requests,
                "get",
                return_value=self._models_response(["gpt-5.2", "gpt-5.1", "gpt-5"]),
            ),
            patch.object(llm_client.requests, "post", return_value=fake_response),
            patch.object(llm_client, "SessionRecorder", return_value=recorder),
        ):
            client = llm_client.LLMClient()
            result = client.chat(
                [{"role": "user", "content": "ping"}],
                stream=True,
                print_callback=lambda *_: None,
                source="chat",
                entrypoint="src/scripts/run_prompt.py",
            )

        self.assertEqual(result["content"], "A")
        recorder.record_request_started.assert_called_once()
        recorder.record_message_snapshot.assert_called_once()
        recorder.record_request_completed.assert_called_once()
        recorder.record_token_count.assert_called_once()
        completed_kwargs = recorder.record_request_completed.call_args.kwargs
        self.assertEqual(completed_kwargs["usage"]["total_tokens"], 10)
        self.assertEqual(completed_kwargs["content"], "A")
        self.assertIsNotNone(completed_kwargs["first_token_latency"])
        self.assertIsNotNone(result["first_token_latency"])

    def test_sync_chat_records_failed_call_with_session_recorder(self):
        recorder = Mock()

        with (
            patch.object(llm_client.Config, "load_env", return_value=None),
            patch.object(llm_client.user_config, "get_active_provider_config", return_value=None),
            patch.dict(os.environ, self._env(), clear=True),
            patch.object(
                llm_client.requests,
                "get",
                return_value=self._models_response(["gpt-5.2", "gpt-5.1", "gpt-5"]),
            ),
            patch.object(
                llm_client.requests,
                "post",
                side_effect=llm_client.requests.RequestException("network down"),
            ),
            patch.object(llm_client, "SessionRecorder", return_value=recorder),
        ):
            client = llm_client.LLMClient()
            with self.assertRaises(llm_client.requests.RequestException):
                client.chat(
                    [{"role": "user", "content": "ping"}],
                    stream=False,
                    source="chat",
                    entrypoint="src/scripts/run_prompt.py",
                )

        recorder.record_request_started.assert_called_once()
        recorder.record_request_failed.assert_called_once()
        failed_kwargs = recorder.record_request_failed.call_args.kwargs
        self.assertIn("network down", str(failed_kwargs["error"]))


if __name__ == "__main__":
    unittest.main()

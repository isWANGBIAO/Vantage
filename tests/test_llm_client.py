import os
import unittest
from unittest.mock import Mock, patch

from src.services import llm_client


class LLMClientTests(unittest.TestCase):
    def _env(self):
        return {
            "CLIPROXYAPI_BASE_URL": "http://127.0.0.1:8317/v1",
            "CLIPROXYAPI_API_KEY": "wb-proxy-2026",
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
            get_patch,
        ):
            return client_cls()

    def test_primary_provider_auto_selects_latest_non_codex_model(self):
        client = self._make_client(
            discovered_models=["gpt-5.1-codex", "gpt-5", "gpt-5.2", "gpt-5.1", "gpt-5.2-codex"],
        )

        self.assertEqual(client.providers[0]["model"], "gpt-5.2")

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

    def test_chat_includes_reasoning_effort_when_configured(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "choices": [{"message": {"content": "done"}}],
            "usage": {},
        }

        with (
            patch.object(llm_client.Config, "load_env", return_value=None),
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


if __name__ == "__main__":
    unittest.main()

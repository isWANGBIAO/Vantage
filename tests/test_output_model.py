import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src import output_model


class OutputModelTests(unittest.TestCase):
    def test_print_model_name_uses_tracked_openai_client(self):
        raw_client = Mock()
        tracked_client = Mock()
        tracked_client.create_chat_completion.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))],
            usage=SimpleNamespace(total_tokens=20),
        )

        with (
            patch.object(output_model, "TrackedOpenAIClient", return_value=tracked_client) as tracked_client_cls,
            patch.object(output_model.time, "time", side_effect=[10.0, 12.0]),
        ):
            output_model.print_model_name(raw_client, "gpt-5.2")

        tracked_client_cls.assert_called_once_with(
            client=raw_client,
            source="output_model",
            entrypoint="src/output_model.py",
        )
        tracked_client.create_chat_completion.assert_called_once()
        kwargs = tracked_client.create_chat_completion.call_args.kwargs
        self.assertEqual(
            kwargs["messages"][1]["content"],
            "你是什么模型？你的资料的最新日期是什么？你的最大上下文是多少个token，为多少K？",
        )
        self.assertNotIn("乱码", kwargs["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()

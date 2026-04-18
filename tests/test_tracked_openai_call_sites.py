import importlib
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.cursor import code_adder
from src.cursor import code_modifier
from src.cursor import error_handler


def _load_analyzer_module():
    fake_modules = {
        "jieba": types.ModuleType("jieba"),
        "numpy": types.ModuleType("numpy"),
        "pandas": types.ModuleType("pandas"),
    }
    tqdm_module = types.ModuleType("tqdm")
    tqdm_module.tqdm = lambda iterable=None, *args, **kwargs: iterable
    fake_modules["tqdm"] = tqdm_module

    with patch.dict(sys.modules, fake_modules):
        existing_module = sys.modules.get("src.AI_Prediction.analyzer")
        if existing_module is not None:
            return importlib.reload(existing_module)
        return importlib.import_module("src.AI_Prediction.analyzer")


def _stream_chunk(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))],
    )


class CursorTrackedOpenAICallSiteTests(unittest.TestCase):
    def test_code_adder_uses_tracked_openai_client(self):
        raw_client = Mock()
        tracked_client = Mock()
        tracked_client.create_chat_completion.return_value = [
            _stream_chunk("```python\nprint('hello')\n```"),
        ]

        with patch.object(code_adder, "TrackedOpenAIClient", return_value=tracked_client) as tracked_client_cls:
            result = code_adder.add_function_code_with_ai("print('hello')", "Python", raw_client, "gpt-5.2")

        tracked_client_cls.assert_called_once_with(
            client=raw_client,
            source="cursor",
            entrypoint="src/cursor/code_adder.py",
        )
        tracked_client.create_chat_completion.assert_called_once()
        self.assertEqual(result, "print('hello')")

    def test_code_modifier_uses_tracked_openai_client(self):
        raw_client = Mock()
        tracked_client = Mock()
        tracked_client.create_chat_completion.return_value = [
            _stream_chunk("```python\nprint('fixed')\n```"),
        ]

        with patch.object(code_modifier, "TrackedOpenAIClient", return_value=tracked_client) as tracked_client_cls:
            result = code_modifier.modify_code_with_ai("print('fixed')", "Python", raw_client, "gpt-5.2")

        tracked_client_cls.assert_called_once_with(
            client=raw_client,
            source="cursor",
            entrypoint="src/cursor/code_modifier.py",
        )
        tracked_client.create_chat_completion.assert_called_once()
        self.assertEqual(result, "print('fixed')")

    def test_error_handler_uses_tracked_openai_client(self):
        raw_client = Mock()
        tracked_client = Mock()
        tracked_client.create_chat_completion.return_value = [
            _stream_chunk("```python\nprint('recovered')\n```"),
        ]

        with patch.object(error_handler, "TrackedOpenAIClient", return_value=tracked_client) as tracked_client_cls:
            result = error_handler.analyze_error_with_ai(
                "print('recovered')",
                "NameError: name 'x' is not defined",
                "Python",
                raw_client,
                "gpt-5.2",
            )

        tracked_client_cls.assert_called_once_with(
            client=raw_client,
            source="cursor",
            entrypoint="src/cursor/error_handler.py",
        )
        tracked_client.create_chat_completion.assert_called_once()
        self.assertEqual(result, "print('recovered')")


class AnalyzerTrackedOpenAICallSiteTests(unittest.TestCase):
    def test_llm_classify_uses_tracked_openai_client(self):
        analyzer = _load_analyzer_module()
        raw_client = Mock()
        tracked_client = Mock()
        tracked_client.create_chat_completion.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"椋熺墿":["鐗涘ザ"],"椁愬巺":[],"娲诲姩":[]}',
                    )
                )
            ]
        )

        with (
            patch.dict(analyzer.os.environ, {"ALIYUN_ACCESS_KEY": "key", "ALIYUN_ACCESS_BASE_URL": "https://example.com"}, clear=False),
            patch.object(analyzer, "OpenAI", return_value=raw_client) as openai_cls,
            patch.object(analyzer, "TrackedOpenAIClient", return_value=tracked_client) as tracked_client_cls,
        ):
            result = analyzer.llm_classify("鐗涘ザ")

        openai_cls.assert_called_once_with(base_url="https://example.com", api_key="key")
        tracked_client_cls.assert_called_once_with(
            client=raw_client,
            source="ai_prediction",
            entrypoint="src/AI_Prediction/analyzer.py",
            base_url="https://example.com",
        )
        tracked_client.create_chat_completion.assert_called_once()
        self.assertEqual(result["椋熺墿"], ["鐗涘ザ"])

    def test_llm_extract_meals_uses_tracked_openai_client(self):
        analyzer = _load_analyzer_module()
        raw_client = Mock()
        tracked_client = Mock()
        tracked_client.create_chat_completion.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"鏃╅":["楦¤泲"],"鍗堥":[],"鏅氶":[],"灏忓悆":[]}',
                    )
                )
            ]
        )

        with (
            patch.dict(analyzer.os.environ, {"ALIYUN_ACCESS_KEY": "key", "ALIYUN_ACCESS_BASE_URL": "https://example.com"}, clear=False),
            patch.object(analyzer, "OpenAI", return_value=raw_client) as openai_cls,
            patch.object(analyzer, "TrackedOpenAIClient", return_value=tracked_client) as tracked_client_cls,
        ):
            result = analyzer.llm_extract_meals("楦¤泲")

        openai_cls.assert_called_once_with(base_url="https://example.com", api_key="key")
        tracked_client_cls.assert_called_once_with(
            client=raw_client,
            source="ai_prediction",
            entrypoint="src/AI_Prediction/analyzer.py",
            base_url="https://example.com",
        )
        tracked_client.create_chat_completion.assert_called_once()
        self.assertEqual(result["鏃╅"], ["楦¤泲"])

    def test_llm_extract_diarrhea_info_uses_tracked_openai_client(self):
        analyzer = _load_analyzer_module()
        raw_client = Mock()
        tracked_client = Mock()
        tracked_client.create_chat_completion.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="[{'娆℃暟': 1, '绋嬪害': '杞诲井', '鏃堕棿': '鏃╀笂'}]",
                    )
                )
            ]
        )

        with (
            patch.dict(analyzer.os.environ, {"ALIYUN_ACCESS_KEY": "key", "ALIYUN_ACCESS_BASE_URL": "https://example.com"}, clear=False),
            patch.object(analyzer, "OpenAI", return_value=raw_client) as openai_cls,
            patch.object(analyzer, "TrackedOpenAIClient", return_value=tracked_client) as tracked_client_cls,
        ):
            result = analyzer.llm_extract_diarrhea_info("鎷夌█ 1 娆?")

        openai_cls.assert_called_once_with(base_url="https://example.com", api_key="key")
        tracked_client_cls.assert_called_once_with(
            client=raw_client,
            source="ai_prediction",
            entrypoint="src/AI_Prediction/analyzer.py",
            base_url="https://example.com",
        )
        tracked_client.create_chat_completion.assert_called_once()
        self.assertEqual(result[0]["娆℃暟"], 1)


if __name__ == "__main__":
    unittest.main()

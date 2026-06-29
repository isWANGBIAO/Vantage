import importlib
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


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


class AnalyzerTrackedOpenAICallSiteTests(unittest.TestCase):
    def test_llm_classify_uses_tracked_openai_client(self):
        analyzer = _load_analyzer_module()
        raw_client = Mock()
        tracked_client = Mock()
        tracked_client.create_chat_completion.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"食物":["牛肉"],"餐厅":[],"活动":[]}',
                    )
                )
            ]
        )

        with (
            patch.dict(
                analyzer.os.environ,
                {"ALIYUN_ACCESS_KEY": "key", "ALIYUN_ACCESS_BASE_URL": "https://example.com"},
                clear=False,
            ),
            patch.object(analyzer, "OpenAI", return_value=raw_client) as openai_cls,
            patch.object(analyzer, "TrackedOpenAIClient", return_value=tracked_client) as tracked_client_cls,
        ):
            result = analyzer.llm_classify("牛肉")

        openai_cls.assert_called_once_with(base_url="https://example.com", api_key="key")
        tracked_client_cls.assert_called_once_with(
            client=raw_client,
            source="ai_prediction",
            entrypoint="src/AI_Prediction/analyzer.py",
            base_url="https://example.com",
        )
        tracked_client.create_chat_completion.assert_called_once()
        self.assertEqual(result["食物"], ["牛肉"])

    def test_llm_extract_meals_uses_tracked_openai_client(self):
        analyzer = _load_analyzer_module()
        raw_client = Mock()
        tracked_client = Mock()
        tracked_client.create_chat_completion.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"早餐":["鸡蛋"],"午餐":[],"晚餐":[],"小吃":[]}',
                    )
                )
            ]
        )

        with (
            patch.dict(
                analyzer.os.environ,
                {"ALIYUN_ACCESS_KEY": "key", "ALIYUN_ACCESS_BASE_URL": "https://example.com"},
                clear=False,
            ),
            patch.object(analyzer, "OpenAI", return_value=raw_client) as openai_cls,
            patch.object(analyzer, "TrackedOpenAIClient", return_value=tracked_client) as tracked_client_cls,
        ):
            result = analyzer.llm_extract_meals("鸡蛋")

        openai_cls.assert_called_once_with(base_url="https://example.com", api_key="key")
        tracked_client_cls.assert_called_once_with(
            client=raw_client,
            source="ai_prediction",
            entrypoint="src/AI_Prediction/analyzer.py",
            base_url="https://example.com",
        )
        tracked_client.create_chat_completion.assert_called_once()
        self.assertEqual(result["早餐"], ["鸡蛋"])

    def test_llm_extract_diarrhea_info_uses_tracked_openai_client(self):
        analyzer = _load_analyzer_module()
        raw_client = Mock()
        tracked_client = Mock()
        tracked_client.create_chat_completion.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="[{'次数': 1, '程度': '轻微', '时间': '早上'}]",
                    )
                )
            ]
        )

        with (
            patch.dict(
                analyzer.os.environ,
                {"ALIYUN_ACCESS_KEY": "key", "ALIYUN_ACCESS_BASE_URL": "https://example.com"},
                clear=False,
            ),
            patch.object(analyzer, "OpenAI", return_value=raw_client) as openai_cls,
            patch.object(analyzer, "TrackedOpenAIClient", return_value=tracked_client) as tracked_client_cls,
        ):
            result = analyzer.llm_extract_diarrhea_info("拉稀 1 次")

        openai_cls.assert_called_once_with(base_url="https://example.com", api_key="key")
        tracked_client_cls.assert_called_once_with(
            client=raw_client,
            source="ai_prediction",
            entrypoint="src/AI_Prediction/analyzer.py",
            base_url="https://example.com",
        )
        tracked_client.create_chat_completion.assert_called_once()
        self.assertEqual(result[0]["次数"], 1)


if __name__ == "__main__":
    unittest.main()

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.services.tracked_openai_client import TrackedOpenAIClient


class _FakeStreamResponse:
    def __init__(self, chunks):
        self._chunks = iter(chunks)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._chunks)


class TrackedOpenAIClientTests(unittest.TestCase):
    def test_sync_completion_records_completed_call(self):
        raw_client = Mock()
        raw_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="done"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4, total_tokens=14),
        )
        recorder = Mock()

        with patch("src.services.tracked_openai_client.SessionRecorder", return_value=recorder):
            client = TrackedOpenAIClient(
                client=raw_client,
                source="output_model",
                entrypoint="src/output_model.py",
            )
            response = client.create_chat_completion(
                model="gpt-5.2",
                messages=[{"role": "user", "content": "ping"}],
                stream=False,
            )

        self.assertEqual(response.choices[0].message.content, "done")
        recorder.record_request_started.assert_called_once()
        recorder.record_message_snapshot.assert_called_once()
        recorder.record_request_completed.assert_called_once()
        recorder.record_token_count.assert_called_once()

    def test_stream_completion_records_completed_call_after_iteration(self):
        raw_client = Mock()
        raw_client.chat.completions.create.return_value = _FakeStreamResponse(
            [
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="A"))],
                    usage=None,
                ),
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="B"))],
                    usage=SimpleNamespace(prompt_tokens=8, completion_tokens=2, total_tokens=10),
                ),
            ]
        )
        recorder = Mock()

        with patch("src.services.tracked_openai_client.SessionRecorder", return_value=recorder):
            client = TrackedOpenAIClient(
                client=raw_client,
                source="cursor",
                entrypoint="src/cursor/code_modifier.py",
            )
            stream = client.create_chat_completion(
                model="gpt-5.2",
                messages=[{"role": "user", "content": "ping"}],
                stream=True,
            )
            content = []
            for chunk in stream:
                content.append(chunk.choices[0].delta.content)

        self.assertEqual("".join(content), "AB")
        recorder.record_request_started.assert_called_once()
        recorder.record_message_snapshot.assert_called_once()
        recorder.record_request_completed.assert_called_once()
        recorder.record_token_count.assert_called_once()
        completed_kwargs = recorder.record_request_completed.call_args.kwargs
        self.assertEqual(completed_kwargs["content"], "AB")
        self.assertEqual(completed_kwargs["usage"]["total_tokens"], 10)

    def test_failed_completion_records_failed_call(self):
        raw_client = Mock()
        raw_client.chat.completions.create.side_effect = RuntimeError("sdk boom")
        recorder = Mock()

        with patch("src.services.tracked_openai_client.SessionRecorder", return_value=recorder):
            client = TrackedOpenAIClient(
                client=raw_client,
                source="ai_prediction",
                entrypoint="src/AI_Prediction/analyzer.py",
            )
            with self.assertRaises(RuntimeError):
                client.create_chat_completion(
                    model="gpt-5.2",
                    messages=[{"role": "user", "content": "ping"}],
                    stream=False,
                )

        recorder.record_request_started.assert_called_once()
        recorder.record_request_failed.assert_called_once()
        failed_kwargs = recorder.record_request_failed.call_args.kwargs
        self.assertIn("sdk boom", str(failed_kwargs["error"]))


if __name__ == "__main__":
    unittest.main()

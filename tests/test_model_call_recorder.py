import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.services.model_call_recorder import SessionRecorder


class SessionRecorderTests(unittest.TestCase):
    def _read_jsonl(self, path):
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_session_recorder_writes_session_meta_line_and_session_row(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_dir = Path(tmpdir) / "history"
            recorder = SessionRecorder(
                session_id="session-chat-1",
                source="chat",
                entrypoint="src/scripts/run_prompt.py",
                history_dir=history_dir,
                default_model="gpt-5.2",
                provider_route="cliproxyapi_primary",
                base_url="http://127.0.0.1:8317/v1",
            )

            rollout_path = recorder.rollout_path
            self.assertTrue(rollout_path.exists())

            lines = self._read_jsonl(rollout_path)
            self.assertEqual(lines[0]["type"], "session_meta")
            self.assertEqual(lines[0]["payload"]["session_id"], "session-chat-1")
            self.assertEqual(lines[0]["payload"]["source"], "chat")
            self.assertEqual(lines[0]["payload"]["entrypoint"], "src/scripts/run_prompt.py")

            conn = sqlite3.connect(history_dir / "state.db")
            try:
                row = conn.execute(
                    "SELECT session_id, source, entrypoint, default_model, provider_route FROM sessions WHERE session_id = ?",
                    ("session-chat-1",),
                ).fetchone()
            finally:
                conn.close()

        self.assertEqual(
            row,
            (
                "session-chat-1",
                "chat",
                "src/scripts/run_prompt.py",
                "gpt-5.2",
                "cliproxyapi_primary",
            ),
        )

    def test_completed_call_persists_jsonl_and_sqlite_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_dir = Path(tmpdir) / "history"
            recorder = SessionRecorder(
                session_id="session-chat-2",
                source="chat",
                entrypoint="src/scripts/run_prompt.py",
                history_dir=history_dir,
            )

            messages = [{"role": "user", "content": "hello"}]
            recorder.record_request_started(
                call_id="call-1",
                model="gpt-5.2",
                provider_route="cliproxyapi_primary",
                stream=False,
                reasoning_effort="medium",
                service_tier="priority",
                messages=messages,
                metadata={"purpose": "test"},
            )
            recorder.record_request_completed(
                call_id="call-1",
                model="gpt-5.2",
                provider_route="cliproxyapi_primary",
                stream=False,
                reasoning_effort="medium",
                service_tier="priority",
                content="world",
                thinking="analysis",
                usage={
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                    "prompt_tokens_details": {
                        "cached_tokens": 4,
                        "audio_tokens": 1,
                    },
                    "completion_tokens_details": {
                        "reasoning_tokens": 3,
                    },
                    "custom_provider_field": {
                        "kept": True,
                    },
                },
                duration=1.25,
                first_token_latency=0.42,
                response={
                    "id": "chatcmpl-call-1",
                    "object": "chat.completion",
                    "system_fingerprint": "fp-test",
                    "usage": {
                        "prompt_tokens": 11,
                        "completion_tokens": 7,
                        "total_tokens": 18,
                        "prompt_tokens_details": {"cached_tokens": 4},
                    },
                    "provider_extra": {"kept": "yes"},
                },
            )
            recorder.record_token_count(
                call_id="call-1",
                last_token_usage={
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                },
            )

            lines = self._read_jsonl(recorder.rollout_path)
            self.assertEqual(
                [line["type"] for line in lines],
                [
                    "session_meta",
                    "request_started",
                    "message_snapshot",
                    "request_completed",
                    "token_count",
                ],
            )
            self.assertEqual(lines[3]["payload"]["content"], "world")
            self.assertEqual(lines[3]["payload"]["first_token_latency"], 0.42)
            self.assertEqual(lines[3]["payload"]["usage"]["prompt_cache_hit_tokens"], 4)
            self.assertEqual(lines[3]["payload"]["usage"]["prompt_cache_miss_tokens"], 7)
            self.assertEqual(lines[3]["payload"]["usage"]["completion_reasoning_tokens"], 3)
            self.assertTrue(lines[3]["payload"]["usage_raw"]["custom_provider_field"]["kept"])
            self.assertEqual(lines[3]["payload"]["response_raw"]["system_fingerprint"], "fp-test")
            self.assertEqual(lines[4]["payload"]["last_token_usage"]["total_tokens"], 18)

            conn = sqlite3.connect(history_dir / "state.db")
            try:
                call_row = conn.execute(
                    """
                    SELECT
                        status, model, provider_route, prompt_tokens, completion_tokens,
                        total_tokens, duration, first_token_latency,
                        prompt_cache_hit_tokens, prompt_cache_miss_tokens,
                        completion_reasoning_tokens, service_tier,
                        usage_json, response_json, request_metadata_json
                    FROM model_calls
                    WHERE call_id = ?
                    """,
                    ("call-1",),
                ).fetchone()
                message_rows = conn.execute(
                    """
                    SELECT message_index, role, content_json
                    FROM session_messages
                    WHERE session_id = ?
                    ORDER BY message_index
                    """,
                    ("session-chat-2",),
                ).fetchall()
            finally:
                conn.close()

        self.assertEqual(
            call_row[:11],
            ("completed", "gpt-5.2", "cliproxyapi_primary", 11, 7, 18, 1.25, 0.42, 4, 7, 3),
        )
        self.assertEqual(call_row[11], "priority")
        usage_json = json.loads(call_row[12])
        response_json = json.loads(call_row[13])
        request_metadata_json = json.loads(call_row[14])
        self.assertEqual(lines[1]["payload"]["service_tier"], "priority")
        self.assertEqual(lines[3]["payload"]["service_tier"], "priority")
        self.assertEqual(usage_json["prompt_tokens_details"]["cached_tokens"], 4)
        self.assertTrue(usage_json["custom_provider_field"]["kept"])
        self.assertEqual(response_json["provider_extra"]["kept"], "yes")
        self.assertEqual(request_metadata_json["purpose"], "test")
        self.assertEqual(len(message_rows), 1)
        self.assertEqual(message_rows[0][0], 0)
        self.assertEqual(message_rows[0][1], "user")
        self.assertEqual(json.loads(message_rows[0][2]), "hello")

    def test_stream_chunks_are_written_to_jsonl_without_full_response_in_sqlite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_dir = Path(tmpdir) / "history"
            recorder = SessionRecorder(
                session_id="session-stream",
                source="chat",
                entrypoint="src/scripts/run_prompt.py",
                history_dir=history_dir,
            )

            recorder.record_request_started(
                call_id="call-stream",
                model="gpt-5.5",
                provider_route="custom",
                stream=True,
                reasoning_effort="high",
                messages=[{"role": "user", "content": "hello"}],
            )
            recorder.record_response_chunk(
                call_id="call-stream",
                chunk={
                    "id": "chunk-1",
                    "object": "chat.completion.chunk",
                    "choices": [{"delta": {"reasoning_content": "think"}}],
                    "system_fingerprint": "fp-stream",
                    "provider_extra": {"kept": True},
                },
            )
            recorder.record_request_completed(
                call_id="call-stream",
                model="gpt-5.5",
                provider_route="custom",
                stream=True,
                reasoning_effort="high",
                content="done",
                thinking="think",
                usage={
                    "prompt_tokens": 20,
                    "completion_tokens": 5,
                    "total_tokens": 25,
                    "prompt_cache_hit_tokens": 8,
                    "prompt_cache_miss_tokens": 12,
                },
                duration=2.0,
            )

            lines = self._read_jsonl(recorder.rollout_path)
            self.assertIn("response_chunk", [line["type"] for line in lines])
            chunk_line = next(line for line in lines if line["type"] == "response_chunk")
            self.assertEqual(chunk_line["payload"]["chunk"]["system_fingerprint"], "fp-stream")
            self.assertTrue(chunk_line["payload"]["chunk"]["provider_extra"]["kept"])

            conn = sqlite3.connect(history_dir / "state.db")
            try:
                row = conn.execute(
                    """
                    SELECT prompt_cache_hit_tokens, prompt_cache_miss_tokens, usage_json, response_json
                    FROM model_calls
                    WHERE call_id = ?
                    """,
                    ("call-stream",),
                ).fetchone()
            finally:
                conn.close()

        self.assertEqual(row[0], 8)
        self.assertEqual(row[1], 12)
        self.assertEqual(json.loads(row[2])["prompt_cache_hit_tokens"], 8)
        self.assertIsNone(row[3])

    def test_failed_call_persists_failure_event_and_sqlite_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_dir = Path(tmpdir) / "history"
            recorder = SessionRecorder(
                session_id="session-chat-3",
                source="chat",
                entrypoint="src/scripts/run_prompt.py",
                history_dir=history_dir,
            )

            recorder.record_request_started(
                call_id="call-error",
                model="gpt-5.2",
                provider_route="cliproxyapi_primary",
                stream=True,
                reasoning_effort="high",
                messages=[{"role": "user", "content": "boom"}],
            )
            recorder.record_request_failed(
                call_id="call-error",
                error=TimeoutError("timed out"),
                model="gpt-5.2",
                provider_route="cliproxyapi_primary",
                stream=True,
                reasoning_effort="high",
                duration=3.0,
            )

            lines = self._read_jsonl(recorder.rollout_path)
            self.assertEqual(lines[-1]["type"], "request_failed")
            self.assertEqual(lines[-1]["payload"]["error_type"], "TimeoutError")
            self.assertIn("timed out", lines[-1]["payload"]["error_message"])

            conn = sqlite3.connect(history_dir / "state.db")
            try:
                row = conn.execute(
                    """
                    SELECT status, error_type, error_message, duration
                    FROM model_calls
                    WHERE call_id = ?
                    """,
                    ("call-error",),
                ).fetchone()
            finally:
                conn.close()

            self.assertEqual(row[0], "failed")
            self.assertEqual(row[1], "TimeoutError")
            self.assertIn("timed out", row[2])
            self.assertEqual(row[3], 3.0)

    def test_failed_call_redacts_provider_api_key_from_history(self):
        secret = "2615cad9be45f50badccd2fa5ffc2bd4596c01eb937c5204388a9c59dfc77b19"
        with tempfile.TemporaryDirectory() as tmpdir:
            history_dir = Path(tmpdir) / "history"
            recorder = SessionRecorder(
                session_id="session-chat-redact",
                source="chat",
                entrypoint="src/scripts/run_prompt.py",
                history_dir=history_dir,
            )

            recorder.record_request_started(
                call_id="call-redact",
                model="deepseek-chat",
                provider_route="SJTU",
                stream=True,
                reasoning_effort="medium",
                messages=[{"role": "user", "content": "boom"}],
            )
            recorder.record_request_failed(
                call_id="call-redact",
                error=RuntimeError(f"Rate limit exceeded for api_key: {secret}"),
                model="deepseek-chat",
                provider_route="SJTU",
                stream=True,
                reasoning_effort="medium",
                duration=1.0,
            )

            lines = self._read_jsonl(recorder.rollout_path)
            self.assertNotIn(secret, lines[-1]["payload"]["error_message"])
            self.assertIn("[REDACTED_API_KEY]", lines[-1]["payload"]["error_message"])

            conn = sqlite3.connect(history_dir / "state.db")
            try:
                row = conn.execute(
                    "SELECT error_message FROM model_calls WHERE call_id = ?",
                    ("call-redact",),
                ).fetchone()
            finally:
                conn.close()

            self.assertNotIn(secret, row[0])
            self.assertIn("[REDACTED_API_KEY]", row[0])


if __name__ == "__main__":
    unittest.main()

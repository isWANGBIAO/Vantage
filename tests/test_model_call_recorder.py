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
                messages=messages,
                metadata={"purpose": "test"},
            )
            recorder.record_request_completed(
                call_id="call-1",
                model="gpt-5.2",
                provider_route="cliproxyapi_primary",
                stream=False,
                reasoning_effort="medium",
                content="world",
                thinking="analysis",
                usage={
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                },
                duration=1.25,
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
            self.assertEqual(lines[4]["payload"]["last_token_usage"]["total_tokens"], 18)

            conn = sqlite3.connect(history_dir / "state.db")
            try:
                call_row = conn.execute(
                    """
                    SELECT status, model, provider_route, prompt_tokens, completion_tokens, total_tokens, duration
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
            call_row,
            ("completed", "gpt-5.2", "cliproxyapi_primary", 11, 7, 18, 1.25),
        )
        self.assertEqual(len(message_rows), 1)
        self.assertEqual(message_rows[0][0], 0)
        self.assertEqual(message_rows[0][1], "user")
        self.assertEqual(json.loads(message_rows[0][2]), "hello")

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


if __name__ == "__main__":
    unittest.main()

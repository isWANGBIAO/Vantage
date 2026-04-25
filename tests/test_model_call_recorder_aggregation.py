import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.services.model_call_recorder import (
    SessionRecorder,
    get_session_usage_summary,
    get_usage_dashboard_snapshot,
)


class SessionRecorderAggregationTests(unittest.TestCase):
    def test_get_session_usage_summary_aggregates_completed_calls_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_dir = Path(tmpdir) / "history"
            recorder = SessionRecorder(
                session_id="session-aggregate-1",
                source="chat",
                entrypoint="src/scripts/run_prompt.py",
                history_dir=history_dir,
            )

            recorder.record_request_started(
                call_id="call-1",
                model="gpt-5.2",
                provider_route="cliproxyapi_primary",
                stream=False,
                reasoning_effort="medium",
                messages=[{"role": "user", "content": "hello"}],
            )
            recorder.record_request_completed(
                call_id="call-1",
                model="gpt-5.2",
                provider_route="cliproxyapi_primary",
                stream=False,
                reasoning_effort="medium",
                content="world",
                thinking="",
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                duration=1.25,
            )

            recorder.record_request_started(
                call_id="call-2",
                model="gpt-5.2",
                provider_route="cliproxyapi_primary",
                stream=True,
                reasoning_effort="high",
                messages=[{"role": "user", "content": "again"}],
            )
            recorder.record_request_completed(
                call_id="call-2",
                model="gpt-5.2",
                provider_route="cliproxyapi_primary",
                stream=True,
                reasoning_effort="high",
                content="done",
                thinking="",
                usage={"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
                duration=2.5,
            )

            recorder.record_request_started(
                call_id="call-err",
                model="gpt-5.2",
                provider_route="cliproxyapi_primary",
                stream=True,
                reasoning_effort="high",
                messages=[{"role": "user", "content": "boom"}],
            )
            recorder.record_request_failed(
                call_id="call-err",
                error=RuntimeError("boom"),
                model="gpt-5.2",
                provider_route="cliproxyapi_primary",
                stream=True,
                reasoning_effort="high",
                duration=9.0,
            )

            summary = get_session_usage_summary(
                "session-aggregate-1",
                db_file=history_dir / "state.db",
            )

        self.assertEqual(summary["session_id"], "session-aggregate-1")
        self.assertEqual(summary["call_count"], 2)
        self.assertEqual(summary["prompt_tokens"], 22)
        self.assertEqual(summary["completion_tokens"], 13)
        self.assertEqual(summary["total_tokens"], 35)
        self.assertAlmostEqual(summary["total_duration"], 3.75)
        self.assertAlmostEqual(summary["average_duration"], 1.875)

    def test_get_usage_dashboard_snapshot_groups_history_for_dashboard(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_dir = Path(tmpdir) / "history"
            chat_recorder = SessionRecorder(
                session_id="session-chat",
                source="chat",
                entrypoint="src/scripts/run_prompt.py",
                history_dir=history_dir,
                default_model="gpt-5.4",
                provider_route="cliproxyapi_primary",
                base_url="http://127.0.0.1:8317/v1",
                created_at=datetime.fromisoformat("2026-04-18T09:00:00+08:00"),
            )
            plan_recorder = SessionRecorder(
                session_id="session-plan",
                source="action_plan",
                entrypoint="src/scripts/run_prompt.py",
                history_dir=history_dir,
                default_model="gpt-5.4",
                provider_route="cliproxyapi_primary",
                base_url="http://127.0.0.1:8317/v1",
                created_at=datetime.fromisoformat("2026-04-17T19:00:00+08:00"),
            )

            with patch(
                "src.services.model_call_recorder._now",
                return_value=datetime.fromisoformat("2026-04-18T09:10:00+08:00"),
            ):
                chat_recorder.record_request_started(
                    call_id="chat-call-1",
                    model="gpt-5.4",
                    provider_route="cliproxyapi_primary",
                    stream=False,
                    reasoning_effort="medium",
                    messages=[{"role": "user", "content": "hello"}],
                )
                chat_recorder.record_request_completed(
                    call_id="chat-call-1",
                    model="gpt-5.4",
                    provider_route="cliproxyapi_primary",
                    stream=False,
                    reasoning_effort="medium",
                    content="world",
                    thinking="",
                    usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                    duration=1.5,
                )

            with patch(
                "src.services.model_call_recorder._now",
                return_value=datetime.fromisoformat("2026-04-18T09:20:00+08:00"),
            ):
                chat_recorder.record_request_started(
                    call_id="chat-call-fail",
                    model="gpt-5.4",
                    provider_route="cliproxyapi_primary",
                    stream=True,
                    reasoning_effort="high",
                    messages=[{"role": "user", "content": "boom"}],
                )
                chat_recorder.record_request_failed(
                    call_id="chat-call-fail",
                    error=RuntimeError("boom"),
                    model="gpt-5.4",
                    provider_route="cliproxyapi_primary",
                    stream=True,
                    reasoning_effort="high",
                    duration=0.75,
                )

            with patch(
                "src.services.model_call_recorder._now",
                return_value=datetime.fromisoformat("2026-04-17T20:00:00+08:00"),
            ):
                plan_recorder.record_request_started(
                    call_id="plan-call-1",
                    model="gpt-5.4",
                    provider_route="cliproxyapi_primary",
                    stream=False,
                    reasoning_effort="high",
                    messages=[{"role": "user", "content": "plan"}],
                )
                plan_recorder.record_request_completed(
                    call_id="plan-call-1",
                    model="gpt-5.4",
                    provider_route="cliproxyapi_primary",
                    stream=False,
                    reasoning_effort="high",
                    content="done",
                    thinking="",
                    usage={"prompt_tokens": 25, "completion_tokens": 15, "total_tokens": 40},
                    duration=2.0,
                )

            snapshot = get_usage_dashboard_snapshot(
                db_file=history_dir / "state.db",
                day_limit=7,
                session_limit=10,
                call_limit=10,
            )

        self.assertEqual(snapshot["summary"]["session_count"], 2)
        self.assertEqual(snapshot["summary"]["completed_call_count"], 2)
        self.assertEqual(snapshot["summary"]["failed_call_count"], 1)
        self.assertEqual(snapshot["summary"]["prompt_tokens"], 35)
        self.assertEqual(snapshot["summary"]["completion_tokens"], 20)
        self.assertEqual(snapshot["summary"]["total_tokens"], 55)
        self.assertAlmostEqual(snapshot["summary"]["total_duration"], 3.5)
        self.assertAlmostEqual(snapshot["summary"]["average_duration"], 1.75)
        self.assertAlmostEqual(snapshot["summary"]["output_tokens_per_second"], 20 / 3.5)

        source_rows = {row["source"]: row for row in snapshot["by_source"]}
        self.assertEqual(source_rows["chat"]["session_count"], 1)
        self.assertEqual(source_rows["chat"]["completed_call_count"], 1)
        self.assertEqual(source_rows["chat"]["failed_call_count"], 1)
        self.assertEqual(source_rows["chat"]["total_tokens"], 15)
        self.assertAlmostEqual(source_rows["chat"]["output_tokens_per_second"], 5 / 1.5)
        self.assertEqual(source_rows["action_plan"]["session_count"], 1)
        self.assertEqual(source_rows["action_plan"]["completed_call_count"], 1)
        self.assertEqual(source_rows["action_plan"]["failed_call_count"], 0)
        self.assertEqual(source_rows["action_plan"]["total_tokens"], 40)
        self.assertAlmostEqual(source_rows["action_plan"]["output_tokens_per_second"], 15 / 2.0)

        self.assertEqual(snapshot["by_day"][0]["date"], "2026-04-18")
        self.assertEqual(snapshot["by_day"][0]["completed_call_count"], 1)
        self.assertEqual(snapshot["by_day"][0]["failed_call_count"], 1)
        self.assertEqual(snapshot["by_day"][0]["total_tokens"], 15)
        self.assertAlmostEqual(snapshot["by_day"][0]["output_tokens_per_second"], 5 / 1.5)
        self.assertEqual(snapshot["by_day"][1]["date"], "2026-04-17")
        self.assertEqual(snapshot["by_day"][1]["completed_call_count"], 1)
        self.assertEqual(snapshot["by_day"][1]["total_tokens"], 40)
        self.assertAlmostEqual(snapshot["by_day"][1]["output_tokens_per_second"], 15 / 2.0)

        self.assertEqual(snapshot["sessions"][0]["session_id"], "session-chat")
        self.assertEqual(snapshot["sessions"][0]["last_status"], "failed")
        self.assertEqual(snapshot["sessions"][0]["completed_call_count"], 1)
        self.assertEqual(snapshot["sessions"][0]["failed_call_count"], 1)
        self.assertEqual(snapshot["sessions"][0]["total_tokens"], 15)
        self.assertAlmostEqual(snapshot["sessions"][0]["output_tokens_per_second"], 5 / 1.5)
        self.assertEqual(snapshot["sessions"][1]["session_id"], "session-plan")
        self.assertEqual(snapshot["sessions"][1]["total_tokens"], 40)
        self.assertAlmostEqual(snapshot["sessions"][1]["output_tokens_per_second"], 15 / 2.0)

        self.assertEqual(snapshot["recent_calls"][0]["call_id"], "chat-call-fail")
        self.assertEqual(snapshot["recent_calls"][0]["status"], "failed")
        self.assertEqual(snapshot["recent_calls"][0]["source"], "chat")
        self.assertEqual(snapshot["recent_calls"][0]["output_tokens_per_second"], 0.0)
        self.assertEqual(snapshot["recent_calls"][1]["call_id"], "chat-call-1")
        self.assertEqual(snapshot["recent_calls"][1]["status"], "completed")
        self.assertEqual(snapshot["recent_calls"][1]["total_tokens"], 15)
        self.assertAlmostEqual(snapshot["recent_calls"][1]["output_tokens_per_second"], 5 / 1.5)
        self.assertEqual(snapshot["recent_calls"][2]["call_id"], "plan-call-1")
        self.assertEqual(snapshot["recent_calls"][2]["source"], "action_plan")

    def test_get_usage_dashboard_snapshot_returns_speed_series_for_completed_duration_calls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_dir = Path(tmpdir) / "history"
            recorder = SessionRecorder(
                session_id="session-speed",
                source="chat",
                entrypoint="src/scripts/run_prompt.py",
                history_dir=history_dir,
                default_model="gpt-5.5",
                provider_route="custom",
                base_url="http://127.0.0.1:8317/v1",
                created_at=datetime.fromisoformat("2026-04-17T08:00:00+08:00"),
            )

            def record_completed(call_id, created_at, duration, usage, *, model="gpt-5.5", reasoning_effort="high"):
                with patch(
                    "src.services.model_call_recorder._now",
                    return_value=datetime.fromisoformat(created_at),
                ):
                    recorder.record_request_started(
                        call_id=call_id,
                        model=model,
                        provider_route="custom",
                        stream=False,
                        reasoning_effort=reasoning_effort,
                        messages=[{"role": "user", "content": call_id}],
                    )
                    recorder.record_request_completed(
                        call_id=call_id,
                        model=model,
                        provider_route="custom",
                        stream=False,
                        reasoning_effort=reasoning_effort,
                        content="done",
                        thinking="",
                        usage=usage,
                        duration=duration,
                    )

            record_completed(
                "old-call",
                "2026-04-17T09:00:00+08:00",
                10.0,
                {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            )
            record_completed(
                "middle-call",
                "2026-04-18T09:00:00+08:00",
                5.0,
                {"prompt_tokens": 80, "completion_tokens": 40, "total_tokens": 120},
                reasoning_effort="medium",
            )
            record_completed(
                "new-call",
                "2026-04-19T09:00:00+08:00",
                4.0,
                {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80},
                model="gpt-5.4",
            )
            record_completed(
                "zero-duration-call",
                "2026-04-20T09:00:00+08:00",
                0.0,
                {"prompt_tokens": 25, "completion_tokens": 25, "total_tokens": 50},
            )

            with patch(
                "src.services.model_call_recorder._now",
                return_value=datetime.fromisoformat("2026-04-21T09:00:00+08:00"),
            ):
                recorder.record_request_started(
                    call_id="failed-call",
                    model="gpt-5.5",
                    provider_route="custom",
                    stream=True,
                    reasoning_effort="high",
                    messages=[{"role": "user", "content": "boom"}],
                )
                recorder.record_request_failed(
                    call_id="failed-call",
                    error=RuntimeError("boom"),
                    model="gpt-5.5",
                    provider_route="custom",
                    stream=True,
                    reasoning_effort="high",
                    duration=2.5,
                )

            snapshot = get_usage_dashboard_snapshot(
                db_file=history_dir / "state.db",
                speed_limit=2,
            )

        self.assertEqual([row["call_id"] for row in snapshot["speed_series"]], ["middle-call", "new-call"])
        self.assertEqual(snapshot["speed_series"][0]["model"], "gpt-5.5")
        self.assertEqual(snapshot["speed_series"][0]["source"], "chat")
        self.assertEqual(snapshot["speed_series"][0]["provider_route"], "custom")
        self.assertEqual(snapshot["speed_series"][0]["reasoning_effort"], "medium")
        self.assertEqual(snapshot["speed_series"][0]["duration"], 5.0)
        self.assertEqual(snapshot["speed_series"][0]["prompt_tokens"], 80)
        self.assertEqual(snapshot["speed_series"][0]["completion_tokens"], 40)
        self.assertEqual(snapshot["speed_series"][0]["total_tokens"], 120)
        self.assertAlmostEqual(snapshot["speed_series"][0]["output_tokens_per_second"], 8.0)
        self.assertAlmostEqual(snapshot["speed_series"][0]["average_tokens_per_second"], 24.0)
        self.assertEqual(snapshot["speed_series"][1]["model"], "gpt-5.4")
        self.assertAlmostEqual(snapshot["speed_series"][1]["output_tokens_per_second"], 7.5)
        self.assertAlmostEqual(snapshot["speed_series"][1]["average_tokens_per_second"], 20.0)


if __name__ == "__main__":
    unittest.main()

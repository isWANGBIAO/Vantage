import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from src.scripts import run_prompt


class _FakeLLMClient:
    def __init__(self):
        self.call_count = 0

    def chat(self, messages, stream=False, print_callback=None, model=None, **kwargs):
        self.call_count += 1

        if self.call_count == 1:
            if print_callback:
                print_callback("content", "analysis reply")
            return {
                "content": "analysis reply",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                "duration": 1.0,
            }

        if print_callback:
            print_callback("content", "plan reply")
        return {
            "content": "plan reply",
            "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
            "duration": 1.5,
        }


class _RetryingFakeLLMClient:
    def __init__(self):
        self.call_count = 0

    def chat(self, messages, stream=False, print_callback=None, model=None, **kwargs):
        self.call_count += 1

        if self.call_count == 1:
            if print_callback:
                print_callback("content", "analysis reply")
            return {
                "content": "analysis reply",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                "duration": 1.0,
            }

        if self.call_count == 2:
            if print_callback:
                print_callback("thinking", "drafting plan")
            return {
                "content": "",
                "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
                "duration": 1.5,
            }

        if print_callback:
            print_callback("content", "plan retry reply")
        return {
            "content": "plan retry reply",
            "usage": {"prompt_tokens": 21, "completion_tokens": 9, "total_tokens": 30},
            "duration": 1.7,
        }


class _CapturingLLMClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, stream=False, print_callback=None, model=None, **kwargs):
        self.calls.append(
            {
                "messages": messages,
                "stream": stream,
                "model": model,
                "kwargs": kwargs,
            }
        )
        response = dict(self.responses.pop(0))
        if print_callback and response.get("content"):
            print_callback("content", response["content"])
        return response


class RunPromptTests(unittest.TestCase):
    def test_format_chat_message_with_timestamp_prefixes_sent_time(self):
        formatted = run_prompt.format_chat_message_with_timestamp(
            "What time is it?",
            "2026-04-08T12:02:03+08:00",
        )

        self.assertIn("Message timestamp: 2026-04-08 12:02:03+08:00", formatted)
        self.assertTrue(formatted.endswith("What time is it?"))

    def test_format_chat_message_with_timestamp_returns_original_message_without_timestamp(self):
        formatted = run_prompt.format_chat_message_with_timestamp(
            "What time is it?",
            None,
        )

        self.assertEqual(formatted, "What time is it?")

    def test_analysis_mode_streams_both_round_prompts(self):
        fake_client = _FakeLLMClient()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            history_dir = temp_path / "history"
            history_dir.mkdir()
            (temp_path / "Prompt_Action_Plan.md").write_text(
                "Now {current_time}\nPast {past_7_days_rows}\nYesterday {yesterday_data_row}\nToday {today_data_row}",
                encoding="utf-8",
            )
            (temp_path / "Prompt_Personal_Info.md").write_text("personal info", encoding="utf-8")
            (temp_path / "Time.xlsx").write_text("placeholder", encoding="utf-8")

            def fake_resolve_data_path(filename):
                return temp_path / filename

            stdout = io.StringIO()

            with patch.object(run_prompt.Config, "load_env"), patch.object(
                run_prompt.Config,
                "get_history_dir",
                return_value=history_dir,
            ), patch.object(
                run_prompt,
                "LLMClient",
                return_value=fake_client,
            ), patch.object(
                run_prompt.DataLoader,
                "construct_prompt",
                return_value="analysis prompt",
            ), patch.object(
                run_prompt.DataLoader,
                "get_system_prompt_content",
                return_value="system prompt",
            ), patch.object(
                run_prompt.DataLoader,
                "resolve_data_path",
                side_effect=fake_resolve_data_path,
            ), patch.object(
                run_prompt.DataLoader,
                "get_past_seven_days_rows",
                return_value="past seven rows",
            ), patch.object(
                run_prompt.DataLoader,
                "get_today_data_row",
                return_value="today row",
            ), patch.object(
                run_prompt.DataLoader,
                "get_yesterday_data_row",
                return_value="yesterday row",
            ), patch.object(
                run_prompt.DataLoader,
                "get_future_planned_rows",
                return_value="2026-06-16（周二）: 工作: 去宁波",
            ), patch.object(
                sys,
                "argv",
                ["run_prompt.py"],
            ), redirect_stdout(stdout):
                run_prompt.main()

            output_lines = stdout.getvalue().splitlines()

        self.assertIn('STREAM_ANALYSIS_SYSTEM:"system prompt"', output_lines)
        self.assertIn('STREAM_ANALYSIS_PROMPT:"analysis prompt"', output_lines)
        plan_prompt_payload = "".join(
            json.loads(line.split(":", 1)[1])
            for line in output_lines
            if line.startswith("STREAM_PLAN_PROMPT:")
        )
        self.assertIn("Past past seven rows", plan_prompt_payload)
        self.assertIn("Yesterday yesterday row", plan_prompt_payload)
        self.assertIn("Today today row", plan_prompt_payload)
        self.assertIn("2026-06-16（周二）: 工作: 去宁波", plan_prompt_payload)

        plan_prompt_index = next(
            index for index, line in enumerate(output_lines)
            if line.startswith('STREAM_PLAN_PROMPT:')
        )
        plan_start_index = output_lines.index('STREAM_PLAN_START:""')
        self.assertLess(plan_prompt_index, plan_start_index)

    def test_analysis_mode_uses_365_days_history_by_default(self):
        fake_client = _FakeLLMClient()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            history_dir = temp_path / "history"
            history_dir.mkdir()
            (temp_path / "Prompt_Action_Plan.md").write_text(
                "Now {current_time}\nPast {past_7_days_rows}\nYesterday {yesterday_data_row}\nToday {today_data_row}",
                encoding="utf-8",
            )
            (temp_path / "Prompt_Personal_Info.md").write_text("personal info", encoding="utf-8")
            (temp_path / "Time.xlsx").write_text("placeholder", encoding="utf-8")

            def fake_resolve_data_path(filename):
                return temp_path / filename

            stdout = io.StringIO()

            with patch.object(run_prompt.Config, "load_env"), patch.object(
                run_prompt.Config,
                "get_history_dir",
                return_value=history_dir,
            ), patch.object(
                run_prompt,
                "LLMClient",
                return_value=fake_client,
            ), patch.object(
                run_prompt.DataLoader,
                "construct_prompt",
                return_value="analysis prompt",
            ) as mock_construct_prompt, patch.object(
                run_prompt.DataLoader,
                "get_system_prompt_content",
                return_value="system prompt",
            ), patch.object(
                run_prompt.DataLoader,
                "resolve_data_path",
                side_effect=fake_resolve_data_path,
            ), patch.object(
                run_prompt.DataLoader,
                "get_past_seven_days_rows",
                return_value="past seven rows",
            ), patch.object(
                run_prompt.DataLoader,
                "get_today_data_row",
                return_value="today row",
            ), patch.object(
                run_prompt.DataLoader,
                "get_yesterday_data_row",
                return_value="yesterday row",
            ), patch.object(
                run_prompt.DataLoader,
                "get_future_planned_rows",
                return_value="2026-06-16（周二）: 工作: 去宁波",
            ), patch.object(
                sys,
                "argv",
                ["run_prompt.py"],
            ), redirect_stdout(stdout):
                run_prompt.main()

        _, kwargs = mock_construct_prompt.call_args
        self.assertEqual(kwargs["days"], 365)

    def test_analysis_mode_persists_structured_json_history(self):
        fake_client = _FakeLLMClient()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            history_dir = temp_path / "history"
            history_dir.mkdir()
            (temp_path / "Prompt_Action_Plan.md").write_text(
                "Now {current_time}\nPast {past_7_days_rows}\nYesterday {yesterday_data_row}\nToday {today_data_row}",
                encoding="utf-8",
            )
            (temp_path / "Prompt_Personal_Info.md").write_text("personal info", encoding="utf-8")
            (temp_path / "Time.xlsx").write_text("placeholder", encoding="utf-8")

            def fake_resolve_data_path(filename):
                return temp_path / filename

            with patch.object(run_prompt.Config, "load_env"), patch.object(
                run_prompt.Config,
                "get_history_dir",
                return_value=history_dir,
            ), patch.object(
                run_prompt,
                "LLMClient",
                return_value=fake_client,
            ), patch.object(
                run_prompt.DataLoader,
                "construct_prompt",
                return_value="analysis prompt",
            ), patch.object(
                run_prompt.DataLoader,
                "get_system_prompt_content",
                return_value="system prompt",
            ), patch.object(
                run_prompt.DataLoader,
                "resolve_data_path",
                side_effect=fake_resolve_data_path,
            ), patch.object(
                run_prompt.DataLoader,
                "get_past_seven_days_rows",
                return_value="past seven rows",
            ), patch.object(
                run_prompt.DataLoader,
                "get_today_data_row",
                return_value="today row",
            ), patch.object(
                run_prompt.DataLoader,
                "get_yesterday_data_row",
                return_value="yesterday row",
            ), patch.object(
                run_prompt.DataLoader,
                "get_future_planned_rows",
                return_value="future rows",
            ), patch.object(
                sys,
                "argv",
                ["run_prompt.py"],
            ):
                run_prompt.main()

            output_files = sorted(history_dir.glob("action_plan_*.json"))
            self.assertEqual(len(output_files), 1)
            self.assertEqual(list(history_dir.glob("action_plan_*.md")), [])
            saved_payload = json.loads(output_files[0].read_text(encoding="utf-8"))

        self.assertEqual(saved_payload["analysis"]["body"], "analysis reply")
        self.assertEqual(saved_payload["plan"]["body"], "plan reply")
        self.assertEqual(saved_payload["meta"]["reasoning_effort"], "medium")
        self.assertIn("generated_at", saved_payload["meta"])
        self.assertEqual(saved_payload["meta"]["stats"]["total_tokens"], 43)

    def test_analysis_mode_retries_plan_round_when_stream_ends_without_content(self):
        fake_client = _RetryingFakeLLMClient()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            history_dir = temp_path / "history"
            history_dir.mkdir()
            (temp_path / "Prompt_Action_Plan.md").write_text(
                "Now {current_time}\nPast {past_7_days_rows}\nYesterday {yesterday_data_row}\nToday {today_data_row}",
                encoding="utf-8",
            )
            (temp_path / "Prompt_Personal_Info.md").write_text("personal info", encoding="utf-8")
            (temp_path / "Time.xlsx").write_text("placeholder", encoding="utf-8")

            def fake_resolve_data_path(filename):
                return temp_path / filename

            stdout = io.StringIO()

            with patch.object(run_prompt.Config, "load_env"), patch.object(
                run_prompt.Config,
                "get_history_dir",
                return_value=history_dir,
            ), patch.object(
                run_prompt,
                "LLMClient",
                return_value=fake_client,
            ), patch.object(
                run_prompt.DataLoader,
                "construct_prompt",
                return_value="analysis prompt",
            ), patch.object(
                run_prompt.DataLoader,
                "get_system_prompt_content",
                return_value="system prompt",
            ), patch.object(
                run_prompt.DataLoader,
                "resolve_data_path",
                side_effect=fake_resolve_data_path,
            ), patch.object(
                run_prompt.DataLoader,
                "get_past_seven_days_rows",
                return_value="past seven rows",
            ), patch.object(
                run_prompt.DataLoader,
                "get_today_data_row",
                return_value="today row",
            ), patch.object(
                run_prompt.DataLoader,
                "get_yesterday_data_row",
                return_value="yesterday row",
            ), patch.object(
                run_prompt.DataLoader,
                "get_future_planned_rows",
                return_value="future rows",
            ), patch.object(
                sys,
                "argv",
                ["run_prompt.py"],
            ), redirect_stdout(stdout):
                run_prompt.main()

            output_lines = stdout.getvalue().splitlines()
            output_files = sorted(history_dir.glob("action_plan_*.json"))
            saved_payload = json.loads(output_files[0].read_text(encoding="utf-8"))

        self.assertEqual(fake_client.call_count, 3)
        self.assertEqual(
            output_lines.count('STREAM_PLAN_START:""'),
            2,
        )
        self.assertEqual(saved_payload["plan"]["body"], "plan retry reply")
        self.assertEqual(saved_payload["meta"]["stats"]["total_tokens"], 73)

    def test_chat_mode_passes_session_metadata_to_llm_client(self):
        fake_client = _CapturingLLMClient(
            [
                {
                    "content": "chat reply",
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
                    "duration": 0.8,
                }
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            history_dir = Path(temp_dir) / "history"
            history_dir.mkdir()

            with patch.object(run_prompt.Config, "load_env"), patch.object(
                run_prompt.Config,
                "get_history_dir",
                return_value=history_dir,
            ), patch.object(
                run_prompt,
                "LLMClient",
                return_value=fake_client,
            ), patch.object(
                run_prompt.DataLoader,
                "get_system_prompt_content",
                return_value="system prompt",
            ), patch.object(
                sys,
                "argv",
                ["run_prompt.py", "--chat_message", "hello"],
            ):
                run_prompt.main()

        self.assertEqual(len(fake_client.calls), 1)
        kwargs = fake_client.calls[0]["kwargs"]
        self.assertEqual(kwargs["source"], "chat")
        self.assertEqual(kwargs["entrypoint"], "src/scripts/run_prompt.py")
        self.assertTrue(kwargs["session_id"])
        self.assertTrue(str(kwargs["context_file"]).endswith("latest_context.json"))

    def test_chat_mode_emits_historical_stats_from_session_summary(self):
        fake_client = _CapturingLLMClient(
            [
                {
                    "content": "chat reply",
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
                    "duration": 0.8,
                }
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            history_dir = Path(temp_dir) / "history"
            history_dir.mkdir()
            stdout = io.StringIO()

            with patch.object(run_prompt.Config, "load_env"), patch.object(
                run_prompt.Config,
                "get_history_dir",
                return_value=history_dir,
            ), patch.object(
                run_prompt,
                "LLMClient",
                return_value=fake_client,
            ), patch.object(
                run_prompt.DataLoader,
                "get_system_prompt_content",
                return_value="system prompt",
            ), patch.object(
                run_prompt,
                "get_session_usage_summary",
                side_effect=[
                    {
                        "session_id": "session-chat-1",
                        "call_count": 4,
                        "prompt_tokens": 70,
                        "completion_tokens": 20,
                        "total_tokens": 90,
                        "total_duration": 12.5,
                        "average_duration": 3.125,
                    },
                    {
                        "session_id": "session-chat-1",
                        "call_count": 5,
                        "prompt_tokens": 75,
                        "completion_tokens": 23,
                        "total_tokens": 98,
                        "total_duration": 13.3,
                        "average_duration": 2.66,
                    },
                ],
            ), patch.object(
                run_prompt,
                "_get_or_create_context_session_id",
                return_value="session-chat-1",
            ), patch.object(
                sys,
                "argv",
                ["run_prompt.py", "--chat_message", "hello"],
            ), redirect_stdout(stdout):
                run_prompt.main()

        stats_lines = [
            json.loads(line.replace("STATS_JSON:", ""))
            for line in stdout.getvalue().splitlines()
            if line.startswith("STATS_JSON:")
        ]

        self.assertEqual(stats_lines[0]["historical_total_tokens"], 90)
        self.assertEqual(stats_lines[-1]["historical_total_tokens"], 98)

    def test_analysis_mode_reuses_same_session_id_for_both_rounds(self):
        fake_client = _CapturingLLMClient(
            [
                {
                    "content": "analysis reply",
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                    "duration": 1.0,
                },
                {
                    "content": "plan reply",
                    "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
                    "duration": 1.5,
                },
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            history_dir = temp_path / "history"
            history_dir.mkdir()
            (temp_path / "Prompt_Action_Plan.md").write_text(
                "Now {current_time}\nPast {past_7_days_rows}\nYesterday {yesterday_data_row}\nToday {today_data_row}",
                encoding="utf-8",
            )
            (temp_path / "Prompt_Personal_Info.md").write_text("personal info", encoding="utf-8")
            (temp_path / "Time.xlsx").write_text("placeholder", encoding="utf-8")

            def fake_resolve_data_path(filename):
                return temp_path / filename

            with patch.object(run_prompt.Config, "load_env"), patch.object(
                run_prompt.Config,
                "get_history_dir",
                return_value=history_dir,
            ), patch.object(
                run_prompt,
                "LLMClient",
                return_value=fake_client,
            ), patch.object(
                run_prompt.DataLoader,
                "construct_prompt",
                return_value="analysis prompt",
            ), patch.object(
                run_prompt.DataLoader,
                "get_system_prompt_content",
                return_value="system prompt",
            ), patch.object(
                run_prompt.DataLoader,
                "resolve_data_path",
                side_effect=fake_resolve_data_path,
            ), patch.object(
                run_prompt.DataLoader,
                "get_past_seven_days_rows",
                return_value="past seven rows",
            ), patch.object(
                run_prompt.DataLoader,
                "get_today_data_row",
                return_value="today row",
            ), patch.object(
                run_prompt.DataLoader,
                "get_yesterday_data_row",
                return_value="yesterday row",
            ), patch.object(
                run_prompt.DataLoader,
                "get_future_planned_rows",
                return_value="future rows",
            ), patch.object(
                sys,
                "argv",
                ["run_prompt.py"],
            ):
                run_prompt.main()

        self.assertEqual(len(fake_client.calls), 2)
        first_kwargs = fake_client.calls[0]["kwargs"]
        second_kwargs = fake_client.calls[1]["kwargs"]
        self.assertEqual(first_kwargs["source"], "action_plan")
        self.assertEqual(second_kwargs["source"], "action_plan")
        self.assertEqual(first_kwargs["entrypoint"], "src/scripts/run_prompt.py")
        self.assertEqual(second_kwargs["entrypoint"], "src/scripts/run_prompt.py")
        self.assertEqual(first_kwargs["session_id"], second_kwargs["session_id"])
        self.assertTrue(first_kwargs["session_id"])

    def test_analysis_mode_uses_session_summary_for_saved_stats(self):
        fake_client = _FakeLLMClient()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            history_dir = temp_path / "history"
            history_dir.mkdir()
            (temp_path / "Prompt_Action_Plan.md").write_text(
                "Now {current_time}\nPast {past_7_days_rows}\nYesterday {yesterday_data_row}\nToday {today_data_row}",
                encoding="utf-8",
            )
            (temp_path / "Prompt_Personal_Info.md").write_text("personal info", encoding="utf-8")
            (temp_path / "Time.xlsx").write_text("placeholder", encoding="utf-8")

            def fake_resolve_data_path(filename):
                return temp_path / filename

            with patch.object(run_prompt.Config, "load_env"), patch.object(
                run_prompt.Config,
                "get_history_dir",
                return_value=history_dir,
            ), patch.object(
                run_prompt,
                "LLMClient",
                return_value=fake_client,
            ), patch.object(
                run_prompt.DataLoader,
                "construct_prompt",
                return_value="analysis prompt",
            ), patch.object(
                run_prompt.DataLoader,
                "get_system_prompt_content",
                return_value="system prompt",
            ), patch.object(
                run_prompt.DataLoader,
                "resolve_data_path",
                side_effect=fake_resolve_data_path,
            ), patch.object(
                run_prompt.DataLoader,
                "get_past_seven_days_rows",
                return_value="past seven rows",
            ), patch.object(
                run_prompt.DataLoader,
                "get_today_data_row",
                return_value="today row",
            ), patch.object(
                run_prompt.DataLoader,
                "get_yesterday_data_row",
                return_value="yesterday row",
            ), patch.object(
                run_prompt.DataLoader,
                "get_future_planned_rows",
                return_value="future rows",
            ), patch.object(
                run_prompt,
                "get_session_usage_summary",
                return_value={
                    "session_id": "session-action-1",
                    "call_count": 2,
                    "prompt_tokens": 42,
                    "completion_tokens": 17,
                    "total_tokens": 59,
                    "total_duration": 3.5,
                    "average_duration": 1.75,
                },
            ), patch.object(
                run_prompt,
                "_create_new_context_session_id",
                return_value="session-action-1",
            ), patch.object(
                sys,
                "argv",
                ["run_prompt.py"],
            ):
                run_prompt.main()

            output_files = sorted(history_dir.glob("action_plan_*.json"))
            saved_payload = json.loads(output_files[0].read_text(encoding="utf-8"))

        self.assertEqual(saved_payload["meta"]["stats"]["prompt_tokens"], 42)
        self.assertEqual(saved_payload["meta"]["stats"]["completion_tokens"], 17)
        self.assertEqual(saved_payload["meta"]["stats"]["total_tokens"], 59)
        self.assertEqual(saved_payload["meta"]["stats"]["historical_total_tokens"], 59)
        self.assertEqual(saved_payload["meta"]["stats"]["total_duration"], 3.5)


if __name__ == "__main__":
    unittest.main()

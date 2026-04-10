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

    def chat(self, messages, stream=False, print_callback=None, model=None):
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
                "Now {current_time}\nYesterday {yesterday_data_row}\nToday {today_data_row}",
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
        self.assertIn("Yesterday yesterday row", plan_prompt_payload)
        self.assertIn("Today today row", plan_prompt_payload)
        self.assertIn("2026-06-16（周二）: 工作: 去宁波", plan_prompt_payload)

        plan_prompt_index = next(
            index for index, line in enumerate(output_lines)
            if line.startswith('STREAM_PLAN_PROMPT:')
        )
        plan_start_index = output_lines.index('---PLAN_START---')
        self.assertLess(plan_prompt_index, plan_start_index)


if __name__ == "__main__":
    unittest.main()

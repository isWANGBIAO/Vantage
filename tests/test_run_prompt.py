import io
import json
import os
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
                "first_token_latency": 0.25,
                "completed_at": "2026-05-04T02:00:01+08:00",
            }

        if print_callback:
            print_callback("content", "plan reply")
        return {
            "content": "plan reply",
            "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
            "duration": 1.5,
            "first_token_latency": 0.4,
            "completed_at": "2026-05-04T02:00:03+08:00",
        }


class _HighButPerRequestSafeLLMClient:
    def __init__(self):
        self.call_count = 0

    def chat(self, messages, stream=False, print_callback=None, model=None, **kwargs):
        self.call_count += 1

        if self.call_count == 1:
            if print_callback:
                print_callback("content", "analysis reply")
            return {
                "content": "analysis reply",
                "usage": {
                    "prompt_tokens": 166400,
                    "completion_tokens": 17400,
                    "total_tokens": 183800,
                },
                "duration": 317.5,
                "first_token_latency": 22.5,
                "completed_at": "2026-06-01T13:12:29+08:00",
            }

        if print_callback:
            print_callback("content", "plan reply")
        return {
            "content": "plan reply",
            "usage": {
                "prompt_tokens": 179400,
                "completion_tokens": 6100,
                "total_tokens": 185500,
            },
            "duration": 114.3,
            "first_token_latency": 8.1,
            "completed_at": "2026-06-01T13:14:23+08:00",
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
                "first_token_latency": 0.25,
                "completed_at": "2026-05-04T02:00:01+08:00",
            }

        if self.call_count == 2:
            if print_callback:
                print_callback("thinking", "drafting plan")
            return {
                "content": "",
                "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
                "duration": 1.5,
                "first_token_latency": 0.6,
                "completed_at": "2026-05-04T02:00:02+08:00",
            }

        if print_callback:
            print_callback("content", "plan retry reply")
        return {
            "content": "plan retry reply",
            "usage": {"prompt_tokens": 21, "completion_tokens": 9, "total_tokens": 30},
            "duration": 1.7,
            "first_token_latency": 0.5,
            "completed_at": "2026-05-04T02:00:04+08:00",
        }


class _IncompleteThenSuccessfulLLMClient:
    def __init__(self):
        self.call_count = 0

    def chat(self, messages, stream=False, print_callback=None, model=None, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            if print_callback:
                print_callback("content", "partial analysis")
            raise run_prompt.StreamIncompleteError("Streaming response ended without a terminal event")

        if print_callback:
            print_callback("content", "complete analysis")
        return {
            "content": "complete analysis",
            "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
            "duration": 2.0,
            "first_token_latency": 0.7,
            "completed_at": "2026-05-10T13:30:00+08:00",
        }


class _AlwaysIncompleteLLMClient:
    def __init__(self):
        self.call_count = 0

    def chat(self, messages, stream=False, print_callback=None, model=None, **kwargs):
        self.call_count += 1
        raise run_prompt.StreamIncompleteError("Streaming response ended without a terminal event")


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


class ActionPlanRequestStatsTests(unittest.TestCase):
    def test_missing_usage_is_marked_unrecorded_instead_of_zero(self):
        stats = run_prompt.build_action_plan_request_stats(
            "analysis",
            {
                "content": "partial stream reply",
                "usage": {},
                "duration": 266.0,
                "first_token_latency": 14.5,
                "completed_at": "2026-05-04T10:59:27+08:00",
                "model": "gpt-5.5",
            },
        )

        self.assertFalse(stats["usage_recorded"])
        self.assertIsNone(stats["prompt_tokens"])
        self.assertIsNone(stats["completion_tokens"])
        self.assertIsNone(stats["total_tokens"])
        self.assertIsNone(stats["prompt_cache_hit_tokens"])
        self.assertIsNone(stats["completion_tokens_per_second"])
        self.assertEqual(stats["duration"], 266.0)
        self.assertEqual(stats["first_token_latency"], 14.5)

    def test_prompt_context_limit_warning_is_recorded_for_large_requests(self):
        stats = run_prompt.build_action_plan_request_stats(
            "analysis",
            {
                "usage": {
                    "prompt_tokens": 250001,
                    "completion_tokens": 42,
                    "total_tokens": 250043,
                },
                "duration": 10.0,
            },
        )

        self.assertEqual(stats["prompt_token_limit"], 250000)
        self.assertTrue(stats["prompt_token_limit_exceeded"])
        self.assertEqual(stats["prompt_context_warning"]["limit"], 250000)
        self.assertEqual(stats["prompt_context_warning"]["prompt_tokens"], 250001)


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

    def test_build_chat_request_messages_keeps_action_plan_prefix_and_full_history(self):
        action_plan_messages = [
            {"role": "system", "content": "stable system"},
            {"role": "user", "content": "analysis input"},
            {"role": "assistant", "content": "analysis reply"},
            {"role": "user", "content": "plan input"},
            {"role": "assistant", "content": "plan reply"},
        ]
        full_history = [
            {"role": "system", "content": "older standalone system"},
            {"role": "user", "content": "older chat"},
            {"role": "assistant", "content": "older reply"},
            {"role": "user", "content": "current message"},
        ]

        messages = run_prompt.build_chat_request_messages(
            full_history,
            action_plan_messages=action_plan_messages,
        )

        self.assertEqual(messages[:5], action_plan_messages)
        self.assertEqual(messages[5:], full_history)
        self.assertEqual(messages[-1]["content"], "current message")
        self.assertEqual(len(messages), len(action_plan_messages) + len(full_history))

    def test_build_chat_request_messages_does_not_duplicate_existing_action_plan_prefix(self):
        action_plan_messages = [
            {"role": "system", "content": "stable system"},
            {"role": "user", "content": "analysis input"},
            {"role": "assistant", "content": "analysis reply"},
            {"role": "user", "content": "plan input"},
            {"role": "assistant", "content": "plan reply"},
        ]
        full_history = action_plan_messages + [
            {"role": "user", "content": "older chat"},
            {"role": "assistant", "content": "older reply"},
            {"role": "user", "content": "current message"},
        ]

        messages = run_prompt.build_chat_request_messages(
            full_history,
            action_plan_messages=action_plan_messages,
        )

        self.assertEqual(messages, full_history)
        self.assertEqual(messages[-1]["content"], "current message")

    def test_run_action_plan_round_retries_incomplete_stream_before_accepting_content(self):
        client = _IncompleteThenSuccessfulLLMClient()

        result, content = run_prompt.run_action_plan_round(
            client=client,
            messages=[{"role": "user", "content": "analysis"}],
            section="analysis",
            model_override="gpt-5.5",
            provider_route="custom",
            service_tier="priority",
            emit_start_before_first_attempt=False,
            max_empty_content_retries=1,
            metadata={},
        )

        self.assertEqual(content, "complete analysis")
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(client.call_count, 2)
        self.assertEqual(result["usage"]["total_tokens"], 18)

    def test_run_action_plan_round_raises_when_incomplete_stream_retries_are_exhausted(self):
        client = _AlwaysIncompleteLLMClient()

        with self.assertRaises(run_prompt.StreamIncompleteError):
            run_prompt.run_action_plan_round(
                client=client,
                messages=[{"role": "user", "content": "analysis"}],
                section="analysis",
                model_override="gpt-5.5",
                provider_route="custom",
                service_tier="priority",
                emit_start_before_first_attempt=False,
                max_empty_content_retries=1,
                metadata={},
            )

        self.assertEqual(client.call_count, 2)

    def test_transcribe_mode_exits_nonzero_when_audio_service_fails(self):
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            sys,
            "argv",
            ["run_prompt.py", "--transcribe", "audio.webm"],
        ), patch.object(run_prompt.Config, "load_env"), patch.object(
            run_prompt.Config,
            "get_history_dir",
            return_value=Path(temp_dir),
        ), patch.object(
            run_prompt.AudioService,
            "transcribe",
            return_value=None,
        ), redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                run_prompt.main()

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("TRANSCRIPTION_ERROR:", stdout.getvalue())

    def test_transcribe_mode_passes_voice_provider_arguments(self):
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            sys,
            "argv",
            [
                "run_prompt.py",
                "--transcribe",
                "audio.webm",
                "--transcribe-base-url",
                "https://voice.example.invalid/v1",
                "--transcribe-api-key",
                "sk-voice",
                "--transcribe-model",
                "sensevoice",
            ],
        ), patch.object(run_prompt.Config, "load_env"), patch.object(
            run_prompt.Config,
            "get_history_dir",
            return_value=Path(temp_dir),
        ), patch.object(
            run_prompt.AudioService,
            "transcribe",
            return_value="hello",
        ) as mock_transcribe, redirect_stdout(stdout):
            run_prompt.main()

        mock_transcribe.assert_called_once_with(
            "audio.webm",
            base_url="https://voice.example.invalid/v1",
            api_key="sk-voice",
            model="sensevoice",
        )
        self.assertIn("TRANSCRIPTION_RESULT:hello", stdout.getvalue())

    def test_transcribe_mode_reads_voice_api_key_from_environment(self):
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            sys,
            "argv",
            [
                "run_prompt.py",
                "--transcribe",
                "audio.webm",
                "--transcribe-base-url",
                "https://voice.example.invalid/v1",
                "--transcribe-model",
                "sensevoice",
            ],
        ), patch.dict(os.environ, {"VANTAGE_TRANSCRIBE_API_KEY": "sk-env-voice"}), patch.object(
            run_prompt.Config,
            "load_env",
        ), patch.object(
            run_prompt.Config,
            "get_history_dir",
            return_value=Path(temp_dir),
        ), patch.object(
            run_prompt.AudioService,
            "transcribe",
            return_value="hello",
        ) as mock_transcribe, redirect_stdout(stdout):
            run_prompt.main()

        mock_transcribe.assert_called_once_with(
            "audio.webm",
            base_url="https://voice.example.invalid/v1",
            api_key="sk-env-voice",
            model="sensevoice",
        )
        self.assertIn("TRANSCRIPTION_RESULT:hello", stdout.getvalue())

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

    def test_analysis_mode_uses_2025_time_series_start_to_fit_proxy_context(self):
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
        self.assertEqual(kwargs["start_date"], "2025-01-01")
        self.assertNotIn("days", kwargs)

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

    def test_analysis_mode_does_not_warn_on_combined_prompt_tokens_when_each_request_fits(self):
        fake_client = _HighButPerRequestSafeLLMClient()

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
            saved_payload = json.loads(output_files[0].read_text(encoding="utf-8"))

        stats = saved_payload["meta"]["stats"]
        self.assertEqual(stats["prompt_tokens"], 345800)
        self.assertFalse(stats["prompt_token_limit_exceeded"])
        self.assertIsNone(stats["prompt_context_warning"])
        for request in stats["requests"]:
            self.assertLess(request["prompt_tokens"], 250000)
            self.assertFalse(request["prompt_token_limit_exceeded"])

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

    def test_chat_mode_sends_action_plan_prefix_before_full_context(self):
        fake_client = _CapturingLLMClient(
            [
                {
                    "content": "chat reply",
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
                    "duration": 0.8,
                }
            ]
        )

        action_plan_messages = [
            {"role": "system", "content": "stable system"},
            {"role": "user", "content": "analysis input"},
            {"role": "assistant", "content": "analysis reply"},
            {"role": "user", "content": "plan input"},
            {"role": "assistant", "content": "plan reply"},
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            history_dir = Path(temp_dir) / "history"
            history_dir.mkdir()
            (history_dir / "latest_context.json").write_text(
                json.dumps(
                    [
                        {"role": "user", "content": "older chat"},
                        {"role": "assistant", "content": "older reply"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (history_dir / "latest_action_plan_context.json").write_text(
                json.dumps(action_plan_messages, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(run_prompt.Config, "load_env"), patch.object(
                run_prompt.Config,
                "get_history_dir",
                return_value=history_dir,
            ), patch.object(
                run_prompt,
                "LLMClient",
                return_value=fake_client,
            ), patch.object(
                sys,
                "argv",
                [
                    "run_prompt.py",
                    "--chat_message",
                    "current",
                    "--client_sent_at",
                    "2026-04-28T01:02:03+08:00",
                ],
            ):
                run_prompt.main()

        sent_messages = fake_client.calls[0]["messages"]
        self.assertEqual(sent_messages[:5], action_plan_messages)
        self.assertEqual(sent_messages[5]["content"], "older chat")
        self.assertEqual(sent_messages[6]["content"], "older reply")
        self.assertTrue(sent_messages[-1]["content"].endswith("\ncurrent"))
        self.assertIn("Message timestamp: 2026-04-28 01:02:03+08:00", sent_messages[-1]["content"])
        self.assertEqual(fake_client.calls[0]["kwargs"]["metadata"]["full_context_message_count"], 3)
        self.assertEqual(fake_client.calls[0]["kwargs"]["metadata"]["sent_context_message_count"], len(sent_messages))
        self.assertEqual(fake_client.calls[0]["kwargs"]["metadata"]["context_strategy"], "action_plan_prefix_full_history")

    def test_chat_mode_passes_provider_route_to_llm_client(self):
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
                ["run_prompt.py", "--chat_message", "hello", "--model", "gpt-5.5", "--provider_route", "custom"],
            ):
                run_prompt.main()

        self.assertEqual(fake_client.calls[0]["model"], "gpt-5.5")
        self.assertEqual(fake_client.calls[0]["kwargs"]["provider_route"], "custom")

    def test_chat_mode_passes_service_tier_to_llm_client(self):
        fake_client = _CapturingLLMClient(
            [
                {
                    "content": "chat reply",
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
                    "duration": 0.8,
                    "service_tier": "priority",
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
                [
                    "run_prompt.py",
                    "--chat_message",
                    "hello",
                    "--model",
                    "gpt-5.5",
                    "--provider_route",
                    "custom",
                    "--service_tier",
                    "priority",
                ],
            ):
                run_prompt.main()

        self.assertEqual(fake_client.calls[0]["kwargs"]["service_tier"], "priority")

    def test_chat_mode_omits_historical_token_stats(self):
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

        self.assertNotIn("historical_total_tokens", stats_lines[0])
        self.assertNotIn("historical_total_tokens", stats_lines[-1])

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

    def test_analysis_mode_passes_time_json_cache_metadata_to_llm_client(self):
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
        analysis_prompt = (
            "## Time Series Data (JSON)\n\n```json\n"
            '{"columns":["date","metric"],"rows":[["2026-04-26",1],["2026-04-27",2]],"latest_values":{"metric":2}}\n'
            "```\n\neditable prompt"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            history_dir = temp_path / "history"
            history_dir.mkdir()
            (temp_path / "Prompt_Action_Plan.md").write_text("plan prompt", encoding="utf-8")
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
                return_value=analysis_prompt,
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

        first_metadata = fake_client.calls[0]["kwargs"]["metadata"]
        second_metadata = fake_client.calls[1]["kwargs"]["metadata"]
        self.assertEqual(first_metadata["cache_layout"], "system_time_json_then_prompts")
        self.assertIn("time_json_rows_hash", first_metadata)
        self.assertIn("time_json_full_hash", first_metadata)
        self.assertIn("prompt_bundle_hash", first_metadata)
        self.assertEqual(second_metadata["time_json_rows_hash"], first_metadata["time_json_rows_hash"])
        self.assertEqual(second_metadata["cache_section"], "plan")

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
        self.assertNotIn("historical_total_tokens", saved_payload["meta"]["stats"])
        self.assertEqual(saved_payload["meta"]["stats"]["total_duration"], 3.5)
        self.assertEqual(saved_payload["meta"]["input"]["system_prompt"], "system prompt")
        self.assertEqual(saved_payload["meta"]["input"]["analysis_prompt"], "analysis prompt")
        self.assertTrue(saved_payload["meta"]["input"]["plan_prompt"].startswith("Now "))
        self.assertEqual(len(saved_payload["meta"]["stats"]["requests"]), 2)
        self.assertEqual(saved_payload["meta"]["stats"]["requests"][0]["section"], "analysis")
        self.assertEqual(saved_payload["meta"]["stats"]["requests"][0]["total_tokens"], 15)
        self.assertEqual(saved_payload["meta"]["stats"]["requests"][0]["first_token_latency"], 0.25)
        self.assertEqual(saved_payload["meta"]["stats"]["requests"][0]["completed_at"], "2026-05-04T02:00:01+08:00")
        self.assertEqual(saved_payload["meta"]["stats"]["requests"][1]["section"], "plan")
        self.assertEqual(saved_payload["meta"]["stats"]["requests"][1]["total_tokens"], 28)
        self.assertEqual(saved_payload["meta"]["stats"]["requests"][1]["first_token_latency"], 0.4)
        self.assertEqual(saved_payload["meta"]["stats"]["requests"][1]["completed_at"], "2026-05-04T02:00:03+08:00")


if __name__ == "__main__":
    unittest.main()

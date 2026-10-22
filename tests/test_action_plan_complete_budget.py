"""Final request boundaries are checked before any provider call."""

import sys
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from src.scripts import run_prompt
from src.utils.prompt_budget import estimate_tokens


def test_round_budget_counts_every_message_including_previous_assistant_output():
    client = Mock()
    client.get_prompt_budget.return_value = {"input_budget_tokens": 50}
    client.chat.return_value = {"content": "synthetic reply", "usage": {}, "duration": 0}
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "initial"}, {"role": "assistant", "content": "A" * 200}, {"role": "user", "content": "daily"}]
    with pytest.raises(ValueError, match="budget"):
        run_prompt.run_action_plan_round(client=client, messages=messages, section="plan", model_override=None, provider_route=None, service_tier=None, emit_start_before_first_attempt=True, emit=lambda _: None)
    client.chat.assert_not_called()


def test_known_second_round_context_and_output_reserve_are_checked_before_first_call(tmp_path):
    (tmp_path / "2_今日行动计划.md").write_text("Daily " * 500, encoding="utf-8")
    history = tmp_path / "history"
    history.mkdir()
    client = Mock()
    client.get_prompt_budget.return_value = {"input_budget_tokens": 500, "output_reserve_tokens": 50}
    client.chat.return_value = {"content": "Long-term plan", "usage": {}, "duration": 0}
    with patch.object(run_prompt.Config, "load_env"), patch.object(run_prompt.Config, "get_history_dir", return_value=history), patch.object(run_prompt, "LLMClient", return_value=client), patch.object(run_prompt.DataLoader, "resolve_data_path", side_effect=lambda name, **_: tmp_path / name), patch.object(run_prompt.DataLoader, "construct_prompt", return_value="Initial synthetic data"), patch.object(run_prompt.DataLoader, "get_system_prompt_content", return_value="System"), patch.object(run_prompt.DataLoader, "get_past_seven_days_rows", return_value="Recent"), patch.object(run_prompt.DataLoader, "get_today_data_row", return_value="Today"), patch.object(run_prompt.DataLoader, "get_yesterday_data_row", return_value="Yesterday"), patch.object(run_prompt.DataLoader, "get_future_planned_rows", return_value="Future"), patch.object(sys, "argv", ["run_prompt.py"]):
        with pytest.raises(SystemExit) as caught:
            run_prompt.main()
    assert caught.value.code == 1
    client.chat.assert_not_called()
    assert not list(history.glob("action_plan_*.json"))


def test_real_excel_long_latest_summary_is_rejected_before_provider_or_publication(tmp_path):
    (tmp_path / "Prompt_Personal_Info.md").write_text("Synthetic private-free instructions", encoding="utf-8")
    (tmp_path / "Prompt_System.md").write_text("Synthetic system", encoding="utf-8")
    today = datetime.now().date()
    pd.DataFrame({"日期": [str(today - timedelta(days=1)), str(today)], "note": ["X" * 30000, None], "metric": [1, 2]}).to_excel(tmp_path / "Time.xlsx", index=False)
    history = tmp_path / "history"
    history.mkdir()
    client = Mock()
    client.get_prompt_budget.return_value = {"input_budget_tokens": 1500, "output_reserve_tokens": 200}
    with patch.object(run_prompt.Config, "load_env"), patch.object(run_prompt.Config, "get_history_dir", return_value=history), patch.object(run_prompt, "LLMClient", return_value=client), patch.object(run_prompt.DataLoader, "resolve_data_path", side_effect=lambda name, **_: tmp_path / name), patch.object(run_prompt.DataLoader, "_build_calendar_info", return_value="Synthetic"), patch.object(sys, "argv", ["run_prompt.py"]):
        with pytest.raises(SystemExit) as caught:
            run_prompt.main()
    assert caught.value.code == 1
    client.chat.assert_not_called()
    assert not list(history.glob("action_plan_*.json"))


def test_real_excel_two_round_input_is_bounded_and_keeps_first_round_context(tmp_path):
    (tmp_path / "Prompt_Personal_Info.md").write_text("Synthetic instructions", encoding="utf-8")
    (tmp_path / "Prompt_System.md").write_text("Synthetic system", encoding="utf-8")
    pd.DataFrame({"日期": [str(datetime.now().date())], "metric": [42]}).to_excel(tmp_path / "Time.xlsx", index=False)
    history = tmp_path / "history"
    history.mkdir()
    client = Mock()
    client.get_prompt_budget.return_value = {"input_budget_tokens": 5000, "output_reserve_tokens": 200}
    sent = []

    def bounded(messages, **kwargs):
        assert estimate_tokens(str(messages)) < 5000
        sent.append([dict(message) for message in messages])
        return {"content": "Long-term synthetic reply" if len(sent) == 1 else "Today synthetic reply", "usage": {}, "duration": 0}

    client.chat.side_effect = bounded
    with patch.object(run_prompt.Config, "load_env"), patch.object(run_prompt.Config, "get_history_dir", return_value=history), patch.object(run_prompt, "LLMClient", return_value=client), patch.object(run_prompt.DataLoader, "resolve_data_path", side_effect=lambda name, **_: tmp_path / name), patch.object(run_prompt.DataLoader, "_build_calendar_info", return_value="Synthetic"), patch.object(sys, "argv", ["run_prompt.py"]):
        run_prompt.main()
    assert len(sent) == 2
    assert sent[1][2] == {"role": "assistant", "content": "Long-term synthetic reply"}
    assert len(list(history.glob("action_plan_*.json"))) == 1


def test_crossing_midnight_cannot_publish_yesterdays_inputs_as_todays_plan(tmp_path):
    class Clock(datetime):
        advanced = False

        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 22, 0, 1) if cls.advanced else cls(2026, 10, 21, 23, 59)

    (tmp_path / "Prompt_Personal_Info.md").write_text("Synthetic instructions", encoding="utf-8")
    (tmp_path / "Prompt_System.md").write_text("Synthetic system", encoding="utf-8")
    pd.DataFrame({"日期": ["2026-10-21"], "metric": [42]}).to_excel(tmp_path / "Time.xlsx", index=False)
    history = tmp_path / "history"
    history.mkdir()
    context = history / "latest_context.json"
    context.write_text('[]', encoding="utf-8")
    original = context.read_bytes()
    client = Mock()
    client.get_prompt_budget.return_value = {"input_budget_tokens": 5000, "output_reserve_tokens": 200}
    calls = 0

    def reply(messages, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            Clock.advanced = True
        return {"content": "Synthetic reply", "usage": {}, "duration": 0}

    client.chat.side_effect = reply
    with patch.object(run_prompt.Config, "load_env"), patch.object(run_prompt.Config, "get_history_dir", return_value=history), patch.object(run_prompt, "LLMClient", return_value=client), patch.object(run_prompt.DataLoader, "resolve_data_path", side_effect=lambda name, **_: tmp_path / name), patch.object(run_prompt.DataLoader, "_build_calendar_info", return_value="Synthetic"), patch.object(run_prompt, "datetime", Clock), patch("src.utils.data_loader.datetime", Clock), patch.object(sys, "argv", ["run_prompt.py", "--context_file", str(context)]):
        with pytest.raises(SystemExit) as caught:
            run_prompt.main()
    assert caught.value.code == 1
    assert calls == 2
    assert not list(history.glob("action_plan_*.json"))
    assert context.read_bytes() == original

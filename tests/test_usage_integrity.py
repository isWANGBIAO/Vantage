"""Synthetic ledger regressions for missing usage and absolute-time cleanup."""

import json
import asyncio
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.services import model_call_recorder as ledger


def record(recorder, call_id, usage, duration=10):
    kwargs = dict(call_id=call_id, model="synthetic", provider_route="test", stream=False, reasoning_effort="medium")
    recorder.record_request_started(**kwargs, messages=[{"role": "user", "content": "synthetic"}])
    recorder.record_request_completed(**kwargs, content="nonempty answer", thinking="", usage=usage, duration=duration)


@pytest.fixture
def recorder(tmp_path):
    return ledger.SessionRecorder(session_id="usage-test", source="chat", entrypoint="test", history_dir=tmp_path)


@pytest.mark.parametrize("legacy", [False, True])
def test_unknown_usage_is_not_zero_and_cannot_dilute_known_speed(recorder, legacy):
    record(recorder, "known", {"prompt_tokens": 50, "completion_tokens": 100, "total_tokens": 150})
    record(recorder, "unknown", {}, duration=90)
    if legacy:
        with sqlite3.connect(recorder.db_file) as conn:
            conn.execute("UPDATE model_calls SET prompt_tokens=0, completion_tokens=0, total_tokens=0 WHERE call_id='unknown'")
    dashboard = ledger.get_usage_dashboard_snapshot(recorder.db_file)
    for aggregate in [dashboard["summary"], dashboard["by_source"][0], dashboard["by_day"][0], dashboard["sessions"][0]]:
        assert aggregate["total_tokens"] == 150
        assert aggregate["usage_complete"] is False
        assert aggregate["usage_missing_call_count"] == 1
        assert aggregate["usage_recorded_call_count"] == 1
        assert aggregate["output_tokens_per_second"] == 10
        assert aggregate["average_tokens_per_second"] == 15
        assert aggregate["average_tokens_per_call"] == 150
        assert aggregate["total_duration"] == 100
    unknown = next(row for row in dashboard["recent_calls"] if row["call_id"] == "unknown")
    assert unknown["total_tokens"] is None
    assert unknown["output_tokens_per_second"] is None
    assert unknown["usage_complete"] is False
    assert [row["call_id"] for row in dashboard["speed_series"]] == ["known"]
    session = ledger.get_session_usage_summary(recorder.session_id, recorder.db_file)
    assert session["usage_missing_call_count"] == 1
    assert session["usage_complete"] is False
    assert session["total_tokens"] == 150


def test_real_zero_usage_is_known_not_missing(recorder):
    record(recorder, "zero", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    payload = ledger.get_usage_dashboard_snapshot(recorder.db_file)
    assert payload["summary"]["usage_complete"] is True
    assert payload["summary"]["usage_missing_call_count"] == 0
    assert payload["recent_calls"][0]["total_tokens"] == 0
    assert payload["recent_calls"][0]["output_tokens_per_second"] == 0


def test_partial_usage_preserves_known_fields_and_field_specific_speed(recorder):
    record(recorder, "partial", {"completion_tokens": 100}, duration=10)
    payload = ledger.get_usage_dashboard_snapshot(recorder.db_file)
    assert payload["summary"]["completion_tokens"] == 100
    assert payload["summary"]["prompt_tokens"] is None
    assert payload["summary"]["total_tokens"] is None
    assert payload["summary"]["output_tokens_per_second"] == 10
    assert payload["summary"]["average_tokens_per_second"] is None
    assert payload["summary"]["usage_missing_call_count"] == 1
    assert payload["recent_calls"][0]["completion_tokens"] == 100
    assert len(payload["speed_series"]) == 1
    assert payload["speed_series"][0]["output_tokens_per_second"] == 10
    assert payload["speed_series"][0]["average_tokens_per_second"] is None


def test_missing_usage_stays_null_in_database_and_rollout(recorder):
    record(recorder, "unknown", {})
    with sqlite3.connect(recorder.db_file) as conn:
        assert conn.execute("SELECT prompt_tokens,completion_tokens,total_tokens FROM model_calls").fetchone() == (None, None, None)
    events = [json.loads(line) for line in recorder.rollout_path.read_text(encoding="utf-8").splitlines()]
    completed = next(event for event in events if event["type"] == "request_completed")
    assert completed["payload"]["usage"]["total_tokens"] is None


@pytest.mark.parametrize("value", [True, -1, 2.5, float("inf"), "not a count"])
def test_invalid_token_count_is_unknown_not_a_true_zero(recorder, value):
    record(recorder, "invalid", {"prompt_tokens": value, "completion_tokens": 5, "total_tokens": 10})
    payload = ledger.get_usage_dashboard_snapshot(recorder.db_file)
    assert payload["recent_calls"][0]["prompt_tokens"] is None
    assert payload["summary"]["usage_complete"] is False


def test_usage_http_contract_preserves_null_and_incomplete_status(recorder, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from src.backend import chat
    record(recorder, "unknown", {})
    monkeypatch.setattr(chat.Config, "get_history_dir", lambda: recorder.db_file.parent)
    app = FastAPI()
    app.include_router(chat.router)

    async def get():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            return await client.get("/api/v1/usage")

    response = asyncio.run(get())
    assert response.status_code == 200
    payload = response.json()
    json.dumps(payload, allow_nan=False)
    assert payload["summary"]["total_tokens"] is None
    assert payload["summary"]["usage_missing_call_count"] == 1
    assert payload["recent_calls"][0]["output_tokens_per_second"] is None


@pytest.mark.parametrize("usage,known", [({}, False), ({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, True)])
def test_chat_cli_does_not_publish_unknown_usage_as_zero(tmp_path, monkeypatch, capsys, usage, known):
    from src.scripts import run_prompt
    monkeypatch.setattr(run_prompt.Config, "load_env", lambda: None)
    monkeypatch.setattr(run_prompt.Config, "get_history_dir", lambda: tmp_path)
    monkeypatch.setattr(run_prompt, "setup_logging", lambda: None)
    monkeypatch.setattr(run_prompt.DataLoader, "get_system_prompt_content", lambda: "synthetic system")
    monkeypatch.setattr(run_prompt, "LLMClient", lambda: SimpleNamespace(chat=lambda *_, **__: {"content": "synthetic answer", "usage": usage, "duration": 3}))
    monkeypatch.setattr(sys, "argv", ["run_prompt.py", "--chat_message=hello", f"--context_file={tmp_path / 'chat.json'}"])
    run_prompt.main()
    stats = [json.loads(line.removeprefix("STATS_JSON:")) for line in capsys.readouterr().out.splitlines() if line.startswith("STATS_JSON:")][-1]
    assert stats["usage_complete"] is known
    assert stats["total_tokens"] == (0 if known else None)
    assert stats["speed"] == ("0.00 tokens/s" if known else None)


@pytest.mark.parametrize("usage,known", [
    ({}, False),
    (None, False),
    ({"completion_tokens": 5}, False),
    ({"prompt_tokens": None, "completion_tokens": 5, "total_tokens": None}, False),
    *[({"prompt_tokens": value, "completion_tokens": 5, "total_tokens": 10}, False)
      for value in (True, -1, 2.5, float("inf"), "not a count")],
    ({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}, True),
])
def test_two_round_cli_accepts_nullable_ledger_summary(tmp_path, monkeypatch, capsys, usage, known):
    from src.scripts import run_prompt
    monkeypatch.setattr(run_prompt.Config, "load_env", lambda: None)
    monkeypatch.setattr(run_prompt.Config, "get_history_dir", lambda: tmp_path)
    monkeypatch.setattr(run_prompt, "setup_logging", lambda: None)
    monkeypatch.setattr(run_prompt.DataLoader, "get_system_prompt_content", lambda: "synthetic system")
    monkeypatch.setattr(run_prompt.DataLoader, "construct_prompt", lambda *_, **__: "synthetic analysis")
    monkeypatch.setattr(run_prompt.DataLoader, "resolve_data_path", lambda name: tmp_path / name)
    for name in ("get_past_seven_days_rows", "get_today_data_row", "get_yesterday_data_row", "get_future_planned_rows"):
        monkeypatch.setattr(run_prompt.DataLoader, name, lambda *_, **__: "synthetic row")
    calls = []

    def chat(*_, **kwargs):
        calls.append(kwargs)
        recorder = ledger.SessionRecorder(session_id=kwargs["session_id"], source="action_plan", entrypoint="test", history_dir=tmp_path)
        record(recorder, f"round-{len(calls)}", usage, duration=3)
        return {"content": f"synthetic round {len(calls)}", "usage": usage, "duration": 3}

    monkeypatch.setattr(run_prompt, "LLMClient", lambda: SimpleNamespace(chat=chat))
    monkeypatch.setattr(sys, "argv", ["run_prompt.py", f"--context_file={tmp_path / 'plan-context.json'}"])
    run_prompt.main()
    assert len(calls) == 2
    stats = [json.loads(line.removeprefix("STATS_JSON:")) for line in capsys.readouterr().out.splitlines() if line.startswith("STATS_JSON:")][-1]
    assert stats["usage_complete"] is known
    assert stats["total_tokens"] == (30 if known else None)
    summary = ledger.get_session_usage_summary(calls[0]["session_id"], tmp_path / "state.db")
    assert summary["usage_complete"] is known
    assert (tmp_path / "latest_action_plan.json").exists() or list(tmp_path.glob("action_plan_*.json"))


@pytest.mark.parametrize("now_text,fresh_text,old_text", [
    ("2026-03-08T03:00:00-04:00", "2026-03-08T01:59:30-05:00", "2026-03-08T00:59:00-05:00"),
    ("2026-11-01T01:30:00-05:00", "2026-11-01T01:29:30-05:00", "2026-11-01T01:29:00-04:00"),
    ("2026-01-01T10:00:00+08:00", "2025-12-31T21:59:30-04:00", "2026-01-01T02:59:00+02:00"),
])
def test_cleanup_compares_instants_across_offset_changes(recorder, now_text, fresh_text, old_text):
    now = datetime.fromisoformat(now_text)
    with sqlite3.connect(recorder.db_file) as conn:
        for call_id, stamp in [("fresh", fresh_text), ("expired", old_text), ("unparseable", "invalid")]:
            conn.execute("INSERT INTO model_calls(call_id,session_id,created_at,status,stream) VALUES(?,?,?,'started',0)", (call_id, recorder.session_id, stamp))
    assert now.astimezone(timezone.utc) - datetime.fromisoformat(fresh_text).astimezone(timezone.utc) == timedelta(seconds=30)
    with patch.object(ledger, "_now", return_value=now):
        assert ledger.repair_abandoned_calls(recorder.db_file, older_than_seconds=3600) == 1
    with sqlite3.connect(recorder.db_file) as conn:
        assert {row[0] for row in conn.execute("SELECT call_id FROM model_calls")} == {"fresh", "unparseable"}
    recorder.record_request_completed(call_id="fresh", model="synthetic", provider_route="test", stream=False, reasoning_effort="medium", content="done", thinking="", usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}, duration=30)
    assert ledger.get_session_usage_summary(recorder.session_id, recorder.db_file)["total_tokens"] == 15


def test_cleanup_cutoff_subtracts_elapsed_time_not_dst_wall_time(recorder):
    now = datetime(2026, 3, 8, 3, 30, tzinfo=ZoneInfo("America/New_York"))
    with sqlite3.connect(recorder.db_file) as conn:
        conn.execute("INSERT INTO model_calls(call_id,session_id,created_at,status,stream) VALUES('active',?,'2026-03-08T01:45:00-05:00','started',0)", (recorder.session_id,))
    with patch.object(ledger, "_now", return_value=now):
        assert ledger.repair_abandoned_calls(recorder.db_file, older_than_seconds=3600) == 0

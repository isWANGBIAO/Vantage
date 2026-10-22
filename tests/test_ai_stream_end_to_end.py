"""Real HTTP providers, run_prompt children, and canonical publication jobs.

Only prompt source loading is replaced for plan cases; all protocol, retry,
process, persistence, and job boundaries are the production implementation.
"""
import asyncio
import json
import os
import sys
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend import action_plans, application, chat, processes
from src.core import user_config
from src.core.config import Config
from src.services.action_plan_jobs import ActionPlanJobService


@pytest.fixture
def isolated_provider(monkeypatch, tmp_path):
    for kind in ("DATA", "CONFIG", "HISTORY", "LOG", "PLOT", "CACHE", "RUNTIME", "MIGRATION"):
        monkeypatch.setenv(f"VANTAGE_{kind}_DIR", str(tmp_path / kind.lower()))
    monkeypatch.setenv("VANTAGE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("AI_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("AI_HEALTH_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    for name in list(os.environ):
        if name.startswith("AI_") and name not in {"AI_DATA_ROOT", "AI_HEALTH_DATA_ROOT"}:
            monkeypatch.delenv(name)
    state = {"calls": [], "responses": []}

    class Provider(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"data": [{"id": "synthetic-model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            state["calls"].append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            records = state["responses"].pop(0)
            body = ("\n\n".join(
                "data: " + (record if isinstance(record, str) else json.dumps(record))
                for record in records
            ) + "\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    user_config.save_provider_config({
        "selected_provider": "synthetic",
        "providers": {"synthetic": {"base_url": f"http://127.0.0.1:{server.server_port}/v1",
                                     "api_key": "synthetic-test-key", "model": "synthetic-model"}},
    })
    yield state
    server.shutdown()
    server.server_close()
    thread.join(5)


def _content(text):
    return {"choices": [{"delta": {"content": text}}]}


def _complete(text="complete reply"):
    return [_content(text), {"choices": [{"delta": {}, "finish_reason": "stop"}]}, "[DONE]"]


@pytest.mark.parametrize("failure", ["empty", "whitespace", "reasoning", "error_done", "partial_error_done", "partial_error_eof"])
def test_failed_chat_never_publishes_partial_or_success(monkeypatch, tmp_path, isolated_provider, failure):
    state = isolated_provider
    if failure == "reasoning":
        records = [{"choices": [{"delta": {"reasoning_content": "reasoning only"}}]}, *_complete("")]
    elif "error" in failure:
        records = ([_content("failed partial")] if failure.startswith("partial") else []) + [
            {"error": {"message": "synthetic provider failure"}}
        ] + (["[DONE]"] if failure.endswith("done") else [])
    else:
        records = _complete("" if failure == "empty" else " \n\t")
    state["responses"] = [records, _complete("successful followup")]
    history = Path(Config.get_history_dir())
    context = history / "latest_context.json"
    original = json.dumps([{"role": "system", "content": "synthetic system"},
                           {"role": "assistant", "content": "old successful answer"}])
    context.write_text(original, encoding="utf-8")
    (history / "latest_context_session.json").write_text(json.dumps({"source": "chat", "session_id": "synthetic"}))
    app = FastAPI()
    app.include_router(chat.router)
    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={"message": "synthetic question"})
        events = [json.loads(line) for line in response.text.splitlines()]
        assert not any(event.get("done") is True for event in events)
        assert any("error" in event or "STREAM_ERROR:" in event.get("log", "") for event in events)
        assert context.read_text(encoding="utf-8") == original
        followup = client.post("/api/v1/chat", json={"message": "--help"})
    assert any(json.loads(line).get("done") for line in followup.text.splitlines())
    assert len(state["calls"]) == 2
    assert not any(message.get("content") == "failed partial" for message in state["calls"][1]["messages"])
    assert state["calls"][1]["messages"][-1]["content"] == "--help"


@pytest.mark.parametrize("section", ["analysis", "plan"])
@pytest.mark.parametrize("recover", [True, False])
def test_plan_retry_runs_through_real_child_and_publication_job(monkeypatch, tmp_path, isolated_provider, section, recover):
    state = isolated_provider
    failed_round = [[_content("partial")], _complete("recovered reply") if recover else [_content("partial again")]]
    state["responses"] = (failed_round + [_complete("final plan")] if section == "analysis"
                          else [_complete("complete analysis")] + failed_round)
    history = Path(Config.get_history_dir())
    original = [{"role": "assistant", "content": "old context"}]
    context = history / "latest_context.json"
    context.write_text(json.dumps(original), encoding="utf-8")
    old_plan = {"id": "old", "date": date.today().isoformat(), "analysis": {"body": "old analysis"}, "plan": {"body": "old plan"}}
    (history / f"action_plan_{date.today():%Y%m%d}_old.json").write_text(json.dumps(old_plan))
    root = Path(chat.__file__).resolve().parents[2]
    child = """
from pathlib import Path
from src.scripts import run_prompt
run_prompt.DataLoader.construct_prompt = lambda *args, **kwargs: '中' * 12000 + '🙂' * 12000
run_prompt.DataLoader.get_system_prompt_content = lambda: 'synthetic system'
run_prompt.DataLoader.resolve_data_path = lambda name: Path(__import__('os').environ['VANTAGE_PROJECT_ROOT']) / name
for name in ('get_past_seven_days_rows', 'get_today_data_row', 'get_yesterday_data_row', 'get_future_planned_rows'):
    setattr(run_prompt.DataLoader, name, lambda *args: 'synthetic daily data')
run_prompt.main()
"""
    monkeypatch.setattr(processes, "_build_run_prompt_subprocess", lambda args: ([sys.executable, "-c", child, *args], str(root)))
    monkeypatch.setattr(action_plans, "_get_missing_action_plan_data_sources", lambda: [])

    async def exercise():
        service = ActionPlanJobService(application._generate, application._read_today)
        try:
            started = await service.start({"replace_today": True})
            result = await asyncio.wait_for(service.wait(started["id"]), timeout=40)
            events = service.events(started["id"])["events"]
            return result, events, await action_plans.get_today_action_plan()
        finally:
            await service.close()

    result, events, saved = asyncio.run(exercise())
    assert result["status"] == ("succeeded" if recover else "failed"), result
    if recover:
        assert saved["id"] != "old"
        assert not any("_ERROR:" in event.get("log", "") for event in events)
        assert json.loads(context.read_text(encoding="utf-8")) != original
    else:
        assert saved["id"] == "old"
        assert json.loads(context.read_text(encoding="utf-8")) == original

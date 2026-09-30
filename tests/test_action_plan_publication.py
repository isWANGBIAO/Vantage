"""Real-file publication boundaries, including crash/restart and midnight."""
import asyncio
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.backend import action_plans, application
from src.core.config import Config
from src.services.action_plan_store import (
    CONTEXT_FILENAMES,
    STAGING_DIRECTORY,
    STAGING_ENV,
    ActionPlanStore,
)


def _payload(identity="new", day=None):
    return {"id": identity, "date": day or date.today().isoformat(),
            "analysis": {"body": f"analysis-{identity}"}, "plan": {"body": f"plan-{identity}"},
            "meta": {"input": {"system_prompt": "private synthetic prompt"}}}


def _save(history, payload, suffix="old"):
    day = payload["date"].replace("-", "")
    path = history / f"action_plan_{day}_{suffix}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _read_both():
    return asyncio.run(action_plans.get_today_action_plan()), asyncio.run(action_plans.get_action_plan_content())


def _fresh_process_reads(history):
    script = (
        "import asyncio,json; from src.backend.action_plans import get_today_action_plan,get_action_plan_content; "
        "print(json.dumps([asyncio.run(get_today_action_plan()),asyncio.run(get_action_plan_content())]))"
    )
    env = {**os.environ, "VANTAGE_HISTORY_DIR": str(history)}
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=True)
    return json.loads(result.stdout.strip())


@pytest.mark.parametrize("has_previous", [False, True])
@pytest.mark.parametrize("failure", ["stream_error", "nonzero", "missing_done", "cancelled", "incomplete"])
def test_unconfirmed_files_never_reach_today_or_content(monkeypatch, tmp_path, has_previous, failure):
    monkeypatch.setattr(Config, "get_history_dir", staticmethod(lambda: tmp_path))
    if has_previous:
        _save(tmp_path, _payload("old"))
    old_context = '[{"role":"assistant","content":"previous context"}]'
    (tmp_path / "latest_context.json").write_text(old_context)
    (tmp_path / "latest_action_plan_context.json").write_text(old_context)
    (tmp_path / "state.db").write_bytes(b"usage remains outside staging")
    observed = []

    async def raw(_request, *, staging_directory):
        async def stream():
            output = _payload()
            if failure == "incomplete":
                output["plan"]["body"] = ""
            (staging_directory / "action_plan.json").write_text(json.dumps(output))
            (staging_directory / "latest_context.json").write_text('[{"role":"assistant","content":"unconfirmed"}]')
            observed.extend([await action_plans.get_today_action_plan(), await action_plans.get_action_plan_content()])
            if failure == "cancelled":
                raise asyncio.CancelledError
            if failure == "stream_error":
                yield json.dumps({"log": 'STREAM_PLAN_ERROR:"failed"'}) + "\n"
                yield '{"done":true}\n'  # Malformed success-after-error must also be rejected.
            elif failure == "nonzero":
                yield '{"error":"subprocess exited with code 1"}\n'
            elif failure == "incomplete":
                yield '{"done":true}\n'
            else:
                yield '{"log":"process exited without a completion event"}\n'
        return SimpleNamespace(body_iterator=stream())

    monkeypatch.setattr(action_plans, "create_action_plan_stream", raw)

    async def exercise():
        return [event async for event in application._generate({"replace_today": True})]

    if failure == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(exercise())
    elif failure == "incomplete":
        with pytest.raises(RuntimeError, match="new complete"):
            asyncio.run(exercise())
    else:
        events = asyncio.run(exercise())
        assert not any(isinstance(event, dict) and event.get("done") for event in events)
    observed.extend(_read_both())
    observed.extend(_fresh_process_reads(tmp_path))
    assert all(item["exists"] is has_previous for item in observed)
    if has_previous:
        assert all(item["id"] == "old" for item in observed)
    assert (tmp_path / "latest_context.json").read_text() == old_context
    assert (tmp_path / "latest_action_plan_context.json").read_text() == old_context
    assert (tmp_path / "state.db").read_bytes() == b"usage remains outside staging"
    assert not list((tmp_path / STAGING_DIRECTORY).iterdir())


@pytest.mark.parametrize("has_previous", [False, True])
def test_crashed_staging_is_invisible_after_fresh_process_reload(monkeypatch, tmp_path, has_previous):
    monkeypatch.setattr(Config, "get_history_dir", staticmethod(lambda: tmp_path))
    if has_previous:
        _save(tmp_path, _payload("old"))
    pending = ActionPlanStore(tmp_path).begin()
    pending.output_file.write_text(json.dumps(_payload()))
    # Simulate process death: deliberately do not publish or discard this session.
    for item in (*_read_both(), *_fresh_process_reads(tmp_path)):
        assert item["exists"] is has_previous
        if has_previous:
            assert item["id"] == "old"
    assert pending.output_file.exists()
    next_pending = ActionPlanStore(tmp_path).begin()
    ActionPlanStore(tmp_path).discard(next_pending)
    assert pending.output_file.exists()  # Cleanup owns only the new invocation.


@pytest.mark.parametrize("replace_today", [False, True])
def test_only_confirmed_success_atomically_publishes_new_file(monkeypatch, tmp_path, replace_today):
    monkeypatch.setattr(Config, "get_history_dir", staticmethod(lambda: tmp_path))
    previous = _save(tmp_path, _payload("old"))
    future = 2_000_000_000_000_000_000
    os.utime(previous, ns=(future, future))
    usage = tmp_path / "state.db"
    usage.write_bytes(b"usage-is-preserved")
    checkpoints = []

    async def raw(request, *, staging_directory):
        assert request.replace_today is False
        async def stream():
            (staging_directory / "action_plan.json").write_text(json.dumps(_payload()))
            for filename in CONTEXT_FILENAMES:
                value = {"session_id": "new-session"} if filename.endswith("_session.json") else [
                    {"role": "assistant", "content": "confirmed context"}]
                (staging_directory / filename).write_text(json.dumps(value))
            checkpoints.append(await action_plans.get_today_action_plan())
            yield '{"done":true}\n'
            checkpoints.append(await action_plans.get_today_action_plan())
        return SimpleNamespace(body_iterator=stream())

    monkeypatch.setattr(action_plans, "create_action_plan_stream", raw)

    async def exercise():
        return [event async for event in application._generate({"replace_today": replace_today})]

    assert asyncio.run(exercise())[-1] == {"done": True}
    assert all(item["id"] == "old" for item in checkpoints)  # Even raw done must exhaust first.
    for item in (*_read_both(), *_fresh_process_reads(tmp_path)):
        assert item["id"] == "new" and item["exists"] is True
    assert previous.exists() is not replace_today
    assert usage.read_bytes() == b"usage-is-preserved"
    assert "confirmed context" in (tmp_path / "latest_context.json").read_text()
    assert json.loads((tmp_path / "latest_context_session.json").read_text())["session_id"] == "new-session"
    assert not list((tmp_path / STAGING_DIRECTORY).iterdir())


def test_midnight_publication_uses_output_date_and_keeps_other_days(tmp_path):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    old = _save(tmp_path, _payload("yesterday", yesterday))
    today_old = _save(tmp_path, _payload("today-old"))
    clock = [yesterday]
    store = ActionPlanStore(tmp_path, today=lambda: clock[0])
    pending = store.begin()
    clock[0] = date.today().isoformat()
    pending.output_file.write_text(json.dumps(_payload()))
    published = store.publish(pending, replace_today=True)
    assert published.path.name.startswith(f"action_plan_{date.today():%Y%m%d}_")
    assert old.exists()
    assert not today_old.exists()
    store.discard(pending)


def test_midnight_rejects_yesterdays_output_without_changing_visible_files(tmp_path):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    old = _save(tmp_path, _payload("today-old"))
    store = ActionPlanStore(tmp_path)
    pending = store.begin()
    pending.output_file.write_text(json.dumps(_payload("stale", yesterday)))
    with pytest.raises(RuntimeError, match="different day"):
        store.publish(pending, replace_today=True)
    assert old.exists() and len(list(tmp_path.glob("action_plan_*.json"))) == 1
    store.discard(pending)


def test_failed_atomic_rename_does_not_change_old_plan_or_context(monkeypatch, tmp_path):
    old = _save(tmp_path, _payload("old"))
    old_context = tmp_path / "latest_context.json"
    old_context.write_text("[]")
    store = ActionPlanStore(tmp_path)
    pending = store.begin()
    pending.output_file.write_text(json.dumps(_payload()))
    (pending.directory / old_context.name).write_text('[{"role":"assistant","content":"new"}]')
    monkeypatch.setattr(os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk unavailable")))
    with pytest.raises(OSError, match="disk unavailable"):
        store.publish(pending, replace_today=True)
    assert old.exists() and old_context.read_text() == "[]"
    store.discard(pending)


def test_raw_factory_passes_internal_staging_without_changing_history(monkeypatch, tmp_path):
    class Process:
        returncode = 0
        stdout = SimpleNamespace(readline=AsyncMock(return_value=b""))
        stderr = SimpleNamespace(readline=AsyncMock(return_value=b""))
        wait = AsyncMock(return_value=0)

    captured = {}
    async def spawn(*args, **kwargs):
        captured.update(kwargs)
        return Process()
    monkeypatch.setattr(action_plans.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(action_plans, "_get_missing_action_plan_data_sources", lambda: [])
    monkeypatch.setenv("VANTAGE_HISTORY_DIR", str(tmp_path / "history"))
    async def exercise():
        response = await action_plans.create_action_plan_stream(staging_directory=tmp_path / "stage")
        return [event async for event in response.body_iterator]
    asyncio.run(exercise())
    assert captured["env"][STAGING_ENV] == str(tmp_path / "stage")
    assert captured["env"]["VANTAGE_HISTORY_DIR"] == str(tmp_path / "history")


def test_real_prompt_entrypoint_stages_plan_and_all_context_but_preserves_usage(monkeypatch, tmp_path, capsys):
    from src.scripts import run_prompt
    from tests.test_run_prompt import _FakeLLMClient

    history = tmp_path / "history"
    history.mkdir()
    store = ActionPlanStore(history)
    pending = store.begin()
    context_before = '[{"role":"assistant","content":"old conversation"}]'
    for name in ("latest_context.json", "latest_action_plan_context.json"):
        (history / name).write_text(context_before)
    (history / "state.db").write_bytes(b"usage-stays-here")
    (tmp_path / "Prompt_Action_Plan.md").write_text("plan prompt")
    (tmp_path / "Time.xlsx").write_text("synthetic workbook placeholder")
    usage_roots = []

    monkeypatch.setattr(run_prompt.Config, "load_env", lambda: None)
    monkeypatch.setattr(run_prompt.Config, "get_history_dir", staticmethod(lambda: history))
    monkeypatch.setattr(run_prompt, "LLMClient", _FakeLLMClient)
    monkeypatch.setattr(run_prompt.DataLoader, "construct_prompt", lambda *args, **kwargs: "analysis prompt")
    monkeypatch.setattr(run_prompt.DataLoader, "get_system_prompt_content", lambda: "system prompt")
    monkeypatch.setattr(run_prompt.DataLoader, "resolve_data_path", lambda name: tmp_path / name)
    for method in ("get_past_seven_days_rows", "get_today_data_row", "get_yesterday_data_row", "get_future_planned_rows"):
        monkeypatch.setattr(run_prompt.DataLoader, method, lambda *args, **kwargs: "synthetic rows")
    monkeypatch.setattr(run_prompt, "_load_session_usage_summary", lambda root, session: usage_roots.append(root))
    monkeypatch.setenv(STAGING_ENV, str(pending.directory))
    monkeypatch.setattr(sys, "argv", ["run_prompt.py"])
    run_prompt.main()
    capsys.readouterr()

    assert pending.output_file.exists()
    assert all((pending.directory / name).exists() for name in CONTEXT_FILENAMES)
    assert not list(history.glob("action_plan_*.json"))
    assert (history / "latest_context.json").read_text() == context_before
    assert (history / "latest_action_plan_context.json").read_text() == context_before
    assert usage_roots == [history]
    assert (history / "state.db").read_bytes() == b"usage-stays-here"
    saved = store.publish(pending)
    assert json.loads(saved.path.read_text())["plan"]["body"] == "plan reply"
    assert "plan reply" in (history / "latest_action_plan_context.json").read_text()
    store.discard(pending)


@pytest.mark.parametrize("outcome", ["nonzero", "stream_error", "success"])
def test_real_child_cannot_publish_before_verified_exit(monkeypatch, tmp_path, outcome):
    from src.backend import processes
    from src.services.action_plan_jobs import ActionPlanJobService

    monkeypatch.setattr(Config, "get_history_dir", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(action_plans, "_get_missing_action_plan_data_sources", lambda: [])
    _save(tmp_path, _payload("old"))
    child_code = (
        "import os,json,sys; from pathlib import Path; "
        f"stage=Path(os.environ[{STAGING_ENV!r}]); "
        f"(stage/'action_plan.json').write_text({json.dumps(_payload())!r}); "
        "print('STREAM_ANALYSIS_CONTENT:\"synthetic progress\"',flush=True); "
    )
    if outcome == "nonzero":
        child_code += "sys.exit(1)"
    elif outcome == "stream_error":
        child_code += "print('STREAM_PLAN_ERROR:\"late failure\"',flush=True)"
    monkeypatch.setattr(processes, "_build_run_prompt_subprocess", lambda args: (
        [sys.executable, "-c", child_code], str(tmp_path)))

    async def exercise():
        jobs = ActionPlanJobService(application._generate, application._read_today, lambda: "synthetic-revision")
        job = await jobs.start({"replace_today": True})
        result = await jobs.wait(job["id"])
        events = jobs.events(job["id"])["events"]
        await jobs.close()
        return result, events

    result, events = asyncio.run(exercise())
    expected = "new" if outcome == "success" else "old"
    assert result["status"] == ("succeeded" if outcome == "success" else "failed")
    assert any(event.get("done") for event in events) is (outcome == "success")
    for item in (*_read_both(), *_fresh_process_reads(tmp_path)):
        assert item["id"] == expected


def test_real_child_cancellation_reaps_process_and_keeps_old_plan(monkeypatch, tmp_path):
    from src.backend import processes
    from src.services.action_plan_jobs import ActionPlanJobService

    monkeypatch.setattr(Config, "get_history_dir", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(action_plans, "_get_missing_action_plan_data_sources", lambda: [])
    _save(tmp_path, _payload("old"))
    child_code = (
        "import os,json,time; from pathlib import Path; "
        f"stage=Path(os.environ[{STAGING_ENV!r}]); "
        f"(stage/'action_plan.json').write_text({json.dumps(_payload())!r}); "
        "print('STREAM_ANALYSIS_CONTENT:\"ready to cancel\"',flush=True); time.sleep(60)"
    )
    monkeypatch.setattr(processes, "_build_run_prompt_subprocess", lambda args: (
        [sys.executable, "-c", child_code], str(tmp_path)))
    children = []
    original_spawn = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        child = await original_spawn(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(action_plans.asyncio, "create_subprocess_exec", spawn)

    async def exercise():
        jobs = ActionPlanJobService(application._generate, application._read_today, lambda: "synthetic-revision")
        try:
            job = await jobs.start({"replace_today": True})
            async with asyncio.timeout(10):
                async for event in jobs.iterate_events(job["id"]):
                    if "ready to cancel" in event.get("log", ""):
                        break
            assert (await action_plans.get_today_action_plan())["id"] == "old"
            result = await jobs.cancel(job["id"])
            assert result["status"] == "cancelled"
        finally:
            await jobs.close()
    asyncio.run(exercise())
    assert children and all(child.returncode is not None for child in children)
    assert all(item["id"] == "old" for item in _fresh_process_reads(tmp_path))
    assert not list((tmp_path / STAGING_DIRECTORY).iterdir())


def test_coarse_filesystem_timestamps_still_select_new_publication(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "get_history_dir", staticmethod(lambda: tmp_path))
    previous = _save(tmp_path, _payload("old"))
    old_time = 2_000_000_000_000_000_000
    os.utime(previous, ns=(old_time, old_time))
    original_utime = os.utime

    def coarse_utime(path, *, ns):
        quantum = 2_000_000_000
        original_utime(path, ns=tuple(value // quantum * quantum for value in ns))

    monkeypatch.setattr(os, "utime", coarse_utime)
    store = ActionPlanStore(tmp_path)
    pending = store.begin()
    pending.output_file.write_text(json.dumps(_payload()))
    published = store.publish(pending)
    assert published.path.stat().st_mtime_ns > previous.stat().st_mtime_ns
    assert all(item["id"] == "new" for item in _read_both())
    store.discard(pending)

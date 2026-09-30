"""Subprocess exit races must not mask cancellation or leave children unreaped."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.backend import chat, processes


class _ExitedProcess:
    def __init__(self):
        self.returncode = None
        self.stdout = SimpleNamespace(readline=AsyncMock(side_effect=asyncio.CancelledError))
        self.stderr = SimpleNamespace(readline=AsyncMock(return_value=b""))
        self.wait_calls = 0

    def terminate(self):
        raise ProcessLookupError("child already exited")

    def kill(self):
        raise ProcessLookupError("child already exited")

    async def wait(self):
        self.wait_calls += 1
        self.returncode = 0
        return 0


def test_process_exit_race_is_still_reaped():
    process = _ExitedProcess()
    processes.terminate_subprocess(process)
    asyncio.run(processes.reap_subprocess(process))
    assert process.wait_calls == 1
    assert process.returncode == 0


def test_chat_cancellation_survives_child_exit_race(monkeypatch, tmp_path):
    process = _ExitedProcess()
    monkeypatch.setattr(chat.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    monkeypatch.setattr(chat, "_get_history_dir", lambda: str(tmp_path))

    async def exercise():
        response = await chat.chat_endpoint(chat.ChatRequest(message="test"))
        with pytest.raises(asyncio.CancelledError):
            await anext(response.body_iterator)

    asyncio.run(exercise())
    assert process.wait_calls == 1


def test_action_plan_cancellation_survives_child_exit_race(monkeypatch, tmp_path):
    from src.backend import action_plans

    process = _ExitedProcess()
    monkeypatch.setattr(action_plans.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    monkeypatch.setattr(action_plans, "_get_missing_action_plan_data_sources", lambda: [])

    async def exercise():
        response = await action_plans.create_action_plan_stream(action_plans.ActionPlanRequest())
        with pytest.raises(asyncio.CancelledError):
            await anext(response.body_iterator)

    asyncio.run(exercise())
    assert process.wait_calls == 1


def test_reaping_already_exited_child_still_waits():
    process = _ExitedProcess()
    process.returncode = 0
    asyncio.run(processes.reap_subprocess(process))
    assert process.wait_calls == 1

"""Subprocess exit races must not mask cancellation or leave children unreaped."""
import asyncio
import sys
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


@pytest.mark.parametrize("fd", [1, 2])
def test_real_paused_output_pipe_does_not_deadlock_reaping(fd):
    async def exercise():
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-c",
            f"import os,time; chunk=b'x'*4095+b'\\n'; [os.write({fd},chunk) for _ in range(10000)]; time.sleep(30)",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stream = process.stdout if fd == 1 else process.stderr
        reaping = None
        try:
            async def wait_for_backpressure():
                while not stream._paused:
                    await asyncio.sleep(0.005)
            await asyncio.wait_for(wait_for_backpressure(), timeout=5)
            reaping = asyncio.create_task(processes.reap_subprocess(process))
            await asyncio.wait_for(asyncio.shield(reaping), timeout=1)
            assert process.returncode is not None
            assert process.stdout.at_eof()
            assert process.stderr.at_eof()
        finally:
            if process.returncode is None:
                process.kill()
            # Test-owned cleanup also lets the original broken helper finish.
            await process.communicate()
            if reaping is not None:
                await reaping

    asyncio.run(exercise())


def test_http_job_cancel_releases_active_slot_with_real_backpressured_child(monkeypatch):
    from datetime import date
    import httpx
    from fastapi import FastAPI
    from src.backend import application
    from src.services.action_plan_jobs import ActionPlanJobService

    async def exercise():
        ready = asyncio.Event()
        children = []

        async def generate(_request):
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-c", "import os,time; [os.write(1,b'x'*4095+b'\\n') for _ in range(10000)]; time.sleep(30)",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            children.append(process)
            try:
                while not process.stdout._paused:
                    await asyncio.sleep(0.005)
                ready.set()
                yield {"log": "synthetic provider waiting"}
                await asyncio.Event().wait()
            finally:
                await processes.reap_subprocess(process)

        service = ActionPlanJobService(generate, lambda: {"exists": False, "date": date.today().isoformat()})
        monkeypatch.setattr(application, "get_services", lambda: SimpleNamespace(jobs=service))
        app = FastAPI()
        app.include_router(application.build_router())
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                first = (await client.post("/api/v1/action-plan/jobs", json={})).json()
                await asyncio.wait_for(ready.wait(), 5)
                cancelled = await asyncio.wait_for(client.post(f"/api/v1/action-plan/jobs/{first['id']}/cancel"), 2)
                assert cancelled.status_code == 200
                assert cancelled.json()["status"] == "cancelled"
                ready.clear()
                second = (await client.post("/api/v1/action-plan/jobs", json={})).json()
                assert second["id"] != first["id"]
                assert not second["reused"]
                await asyncio.wait_for(ready.wait(), 5)
                await asyncio.wait_for(service.cancel(second["id"]), 2)
                assert all(child.returncode is not None for child in children)
        finally:
            for child in children:
                if child.returncode is None:
                    child.kill()
                await child.communicate()
            await service.close()

    asyncio.run(exercise())

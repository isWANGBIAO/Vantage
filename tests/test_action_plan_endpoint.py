import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from src import server


class _FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)

    async def readline(self):
        if self._lines:
            return self._lines.pop(0)
        return b""


class _FakeProcess:
    def __init__(self, lines=None, returncode=0):
        self.stdout = _FakeStdout(lines or [b'STREAM_ANALYSIS_CONTENT:"ok"\n'])
        self.stderr = AsyncMock()
        self.returncode = returncode

    async def wait(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


async def _read_first_stream_chunk(response):
    async for chunk in response.body_iterator:
        return chunk
    return None


class ActionPlanEndpointTests(unittest.TestCase):
    def test_generate_action_plan_passes_reasoning_effort_to_subprocess(self):
        fake_process = _FakeProcess()

        with patch.object(
            server.asyncio,
            "create_subprocess_exec",
            AsyncMock(return_value=fake_process),
        ) as mock_create:
            response = asyncio.run(
                server.generate_action_plan(
                    server.ActionPlanRequest(reasoning_effort="high"),
                ),
            )
            chunk = asyncio.run(_read_first_stream_chunk(response))

        self.assertIn('STREAM_ANALYSIS_CONTENT', chunk)
        self.assertEqual(mock_create.await_args.kwargs["env"]["AI_REASONING_EFFORT"], "high")

    def test_generate_action_plan_defaults_reasoning_effort_to_medium(self):
        fake_process = _FakeProcess()

        with patch.object(
            server.asyncio,
            "create_subprocess_exec",
            AsyncMock(return_value=fake_process),
        ) as mock_create:
            response = asyncio.run(server.generate_action_plan())
            asyncio.run(_read_first_stream_chunk(response))

        self.assertEqual(mock_create.await_args.kwargs["env"]["AI_REASONING_EFFORT"], "medium")

    def test_generate_action_plan_rejects_invalid_reasoning_effort(self):
        fake_process = _FakeProcess()

        with patch.object(
            server.asyncio,
            "create_subprocess_exec",
            AsyncMock(return_value=fake_process),
        ) as mock_create:
            response = asyncio.run(
                server.generate_action_plan(
                    server.ActionPlanRequest(reasoning_effort="invalid"),
                ),
            )
            asyncio.run(_read_first_stream_chunk(response))

        self.assertEqual(mock_create.await_args.kwargs["env"]["AI_REASONING_EFFORT"], "medium")


if __name__ == "__main__":
    unittest.main()

import asyncio
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
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
    def __init__(self, lines=None, returncode=0, stderr_data=b""):
        self.stdout = _FakeStdout(lines or [b'STREAM_ANALYSIS_CONTENT:"ok"\n'])
        self.stderr = AsyncMock()
        self.stderr.read = AsyncMock(return_value=stderr_data)
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


async def _read_all_stream_chunks(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    return chunks


class ActionPlanEndpointTests(unittest.TestCase):
    def test_generate_action_plan_replace_today_deletes_older_today_files_after_success(self):
        today = datetime.now().strftime("%Y%m%d")

        with tempfile.TemporaryDirectory() as temp_dir:
            history_dir = Path(temp_dir) / "history"
            history_dir.mkdir()

            old_file_a = history_dir / f"action_plan_{today}_010101.md"
            old_file_b = history_dir / f"action_plan_{today}_020202.md"
            new_file = history_dir / f"action_plan_{today}_030303.md"
            old_file_a.write_text("old a", encoding="utf-8")
            old_file_b.write_text("old b", encoding="utf-8")

            async def fake_create_subprocess_exec(*args, **kwargs):
                new_file.write_text("new", encoding="utf-8")
                return _FakeProcess(returncode=0)

            with patch.object(server.os, "getcwd", return_value=temp_dir), patch.object(
                server.asyncio,
                "create_subprocess_exec",
                AsyncMock(side_effect=fake_create_subprocess_exec),
            ):
                response = asyncio.run(
                    server.generate_action_plan(
                        server.ActionPlanRequest(replace_today=True),
                    ),
                )
                asyncio.run(_read_all_stream_chunks(response))

            self.assertFalse(old_file_a.exists())
            self.assertFalse(old_file_b.exists())
            self.assertTrue(new_file.exists())

    def test_generate_action_plan_replace_today_keeps_existing_files_when_process_fails(self):
        today = datetime.now().strftime("%Y%m%d")

        with tempfile.TemporaryDirectory() as temp_dir:
            history_dir = Path(temp_dir) / "history"
            history_dir.mkdir()

            old_file_a = history_dir / f"action_plan_{today}_010101.md"
            old_file_b = history_dir / f"action_plan_{today}_020202.md"
            old_file_a.write_text("old a", encoding="utf-8")
            old_file_b.write_text("old b", encoding="utf-8")

            with patch.object(server.os, "getcwd", return_value=temp_dir), patch.object(
                server.asyncio,
                "create_subprocess_exec",
                AsyncMock(return_value=_FakeProcess(lines=[], returncode=1, stderr_data=b"boom")),
            ):
                response = asyncio.run(
                    server.generate_action_plan(
                        server.ActionPlanRequest(replace_today=True),
                    ),
                )
                asyncio.run(_read_all_stream_chunks(response))

            self.assertTrue(old_file_a.exists())
            self.assertTrue(old_file_b.exists())

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

    def test_generate_action_plan_runs_subprocess_unbuffered_for_streaming(self):
        fake_process = _FakeProcess()

        with patch.object(
            server.asyncio,
            "create_subprocess_exec",
            AsyncMock(return_value=fake_process),
        ) as mock_create:
            response = asyncio.run(server.generate_action_plan())
            asyncio.run(_read_first_stream_chunk(response))

        self.assertEqual(mock_create.await_args.kwargs["env"]["PYTHONUNBUFFERED"], "1")

    def test_generate_action_plan_does_not_stream_stderr_logs_on_success(self):
        async def fake_create_subprocess_exec(*args, **kwargs):
            if kwargs["stderr"] == server.asyncio.subprocess.STDOUT:
                return _FakeProcess(
                    lines=[
                        b'2026-03-08 14:58:33 - INFO - LLM route cliproxyapi_primary succeeded with model gpt-5.2 at http://127.0.0.1:8317/v1\n',
                        b'STREAM_ANALYSIS_CONTENT:"ok"\n',
                    ],
                    returncode=0,
                )

            return _FakeProcess(
                lines=[b'STREAM_ANALYSIS_CONTENT:"ok"\n'],
                returncode=0,
                stderr_data=b'2026-03-08 14:58:33 - INFO - LLM route cliproxyapi_primary succeeded with model gpt-5.2 at http://127.0.0.1:8317/v1\n',
            )

        with patch.object(
            server.asyncio,
            "create_subprocess_exec",
            AsyncMock(side_effect=fake_create_subprocess_exec),
        ):
            response = asyncio.run(server.generate_action_plan())
            chunks = asyncio.run(_read_all_stream_chunks(response))

        combined = "".join(chunks)
        self.assertIn('STREAM_ANALYSIS_CONTENT', combined)
        self.assertNotIn('LLM route cliproxyapi_primary succeeded', combined)

    def test_generate_action_plan_streams_stderr_as_error_when_process_fails(self):
        fake_process = _FakeProcess(
            lines=[],
            returncode=1,
            stderr_data=b"fatal action plan error",
        )

        with patch.object(
            server.asyncio,
            "create_subprocess_exec",
            AsyncMock(return_value=fake_process),
        ):
            response = asyncio.run(server.generate_action_plan())
            chunks = asyncio.run(_read_all_stream_chunks(response))

        combined = "".join(chunks)
        self.assertIn('"error": "fatal action plan error"', combined)


if __name__ == "__main__":
    unittest.main()

import asyncio
import json
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


class _CancelOnReadStdout:
    async def readline(self):
        raise asyncio.CancelledError()


class _FakeProcess:
    def __init__(self, lines=None, returncode=0, stderr_data=b""):
        self.stdout = _FakeStdout(lines or [b'STREAM_ANALYSIS_CONTENT:"ok"\n'])
        self.stderr = AsyncMock()
        self.stderr.read = AsyncMock(return_value=stderr_data)
        self.returncode = returncode
        self.communicate = AsyncMock(return_value=(b"", stderr_data))

    async def wait(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


class _CancelableProcess:
    def __init__(self):
        self.stdout = _CancelOnReadStdout()
        self.stderr = AsyncMock()
        self.stderr.read = AsyncMock(return_value=b"")
        self.returncode = None
        self.terminate_called = False
        self.kill_called = False

    async def wait(self):
        return self.returncode

    def terminate(self):
        self.terminate_called = True

    def kill(self):
        self.kill_called = True
        self.returncode = -9


class _FakeUploadFile:
    def __init__(self, filename="recording.webm", content=b"audio-bytes"):
        self.filename = filename
        self._content = content

    async def read(self):
        return self._content


async def _read_first_stream_chunk(response):
    while True:
        try:
            return await anext(response.body_iterator)
        except StopAsyncIteration:
            return None
    return None


async def _read_all_stream_chunks(response):
    chunks = []
    while True:
        try:
            chunk = await anext(response.body_iterator)
        except StopAsyncIteration:
            break
        chunks.append(chunk)
    return chunks


async def _consume_response_body(response):
    while True:
        try:
            await anext(response.body_iterator)
        except StopAsyncIteration:
            break


class ActionPlanEndpointTests(unittest.TestCase):
    def test_server_keeps_debug_suite_endpoints_registered(self):
        route_paths = {route.path for route in server.app.routes}

        self.assertIn("/api/action_plan_content", route_paths)
        self.assertIn("/api/system_logs", route_paths)

    def test_image_proxy_rejects_sibling_directory_with_same_prefix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            allowed_dir = Path(temp_dir) / "photos"
            sibling_dir = Path(temp_dir) / "photos_evil"
            allowed_dir.mkdir()
            sibling_dir.mkdir()

            target = sibling_dir / "secret.jpg"
            target.write_bytes(b"fake-image")

            with patch.object(server.state, "photos_path", str(allowed_dir)), patch.object(
                server.state,
                "screenshots_path",
                None,
            ):
                response = asyncio.run(server.image_proxy(str(target)))

            self.assertEqual(response.status_code, 403)

    def test_chat_endpoint_cleans_up_subprocess_when_stream_is_cancelled(self):
        fake_process = _CancelableProcess()

        with patch.object(
            server.asyncio,
            "create_subprocess_exec",
            AsyncMock(return_value=fake_process),
        ):
            response = asyncio.run(
                server.chat_endpoint(
                    server.ChatRequest(message="hello"),
                ),
            )

            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(_consume_response_body(response))

        self.assertTrue(fake_process.terminate_called)
        self.assertTrue(fake_process.kill_called)

    def test_transcribe_audio_removes_temp_file_when_subprocess_spawn_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixed_time = 1234567890
            expected_temp_file = Path(temp_dir) / f"temp_audio_{fixed_time}.webm"
            original_abspath = server.os.path.abspath

            def fake_abspath(path):
                if path == server.__file__:
                    return os.path.join(temp_dir, "src", "server.py")
                return original_abspath(path)

            with patch.object(server.time, "time", return_value=fixed_time), patch.object(
                server.os.path,
                "abspath",
                side_effect=fake_abspath,
            ), patch.object(
                server.asyncio,
                "create_subprocess_exec",
                AsyncMock(side_effect=RuntimeError("spawn failed")),
            ):
                with self.assertRaises(RuntimeError):
                    asyncio.run(server.transcribe_audio(_FakeUploadFile()))

            self.assertFalse(expected_temp_file.exists())

    def test_transcribe_audio_removes_temp_file_when_communicate_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixed_time = 1234567891
            expected_temp_file = Path(temp_dir) / f"temp_audio_{fixed_time}.webm"
            original_abspath = server.os.path.abspath

            def fake_abspath(path):
                if path == server.__file__:
                    return os.path.join(temp_dir, "src", "server.py")
                return original_abspath(path)

            fake_process = _FakeProcess()
            fake_process.communicate = AsyncMock(side_effect=RuntimeError("communicate failed"))

            with patch.object(server.time, "time", return_value=fixed_time), patch.object(
                server.os.path,
                "abspath",
                side_effect=fake_abspath,
            ), patch.object(
                server.asyncio,
                "create_subprocess_exec",
                AsyncMock(return_value=fake_process),
            ):
                with self.assertRaises(RuntimeError):
                    asyncio.run(server.transcribe_audio(_FakeUploadFile()))

            self.assertFalse(expected_temp_file.exists())

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

    def test_get_chat_context_reports_action_plan_base_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history_dir = Path(temp_dir) / "history"
            history_dir.mkdir()
            base_context = history_dir / "latest_action_plan_context.json"
            base_context.write_text(
                json.dumps(
                    [
                        {"role": "system", "content": "hidden"},
                        {"role": "user", "content": "analysis prompt"},
                        {"role": "assistant", "content": "analysis result"},
                        {"role": "user", "content": "plan prompt"},
                        {"role": "assistant", "content": "plan result"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(server.os, "getcwd", return_value=temp_dir):
                payload = asyncio.run(server.get_chat_context())

        self.assertEqual(payload["has_action_plan_context"], True)
        self.assertTrue(payload["base_context_version"])
        self.assertEqual(
            payload["display_messages"],
            [
                {"role": "assistant", "content": "analysis result"},
                {"role": "assistant", "content": "plan result"},
            ],
        )

    def test_reset_chat_context_restores_latest_action_plan_seed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history_dir = Path(temp_dir) / "history"
            history_dir.mkdir()
            latest_context = history_dir / "latest_context.json"
            action_plan_context = history_dir / "latest_action_plan_context.json"

            seed_messages = [
                {"role": "system", "content": "seed system"},
                {"role": "assistant", "content": "seed plan"},
            ]
            latest_context.write_text(
                json.dumps(seed_messages + [{"role": "user", "content": "stale chat"}], ensure_ascii=False),
                encoding="utf-8",
            )
            action_plan_context.write_text(
                json.dumps(seed_messages, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(server.os, "getcwd", return_value=temp_dir):
                payload = asyncio.run(server.reset_chat_context())

            restored_messages = json.loads(latest_context.read_text(encoding="utf-8"))

        self.assertEqual(restored_messages, seed_messages)
        self.assertEqual(payload["has_action_plan_context"], True)
        self.assertTrue(payload["base_context_version"])
        self.assertEqual(
            payload["display_messages"],
            [{"role": "assistant", "content": "seed plan"}],
        )

    def test_reset_chat_context_clears_history_when_no_action_plan_seed_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history_dir = Path(temp_dir) / "history"
            history_dir.mkdir()
            latest_context = history_dir / "latest_context.json"
            latest_context.write_text(
                json.dumps([{"role": "user", "content": "stale chat"}], ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(server.os, "getcwd", return_value=temp_dir):
                payload = asyncio.run(server.reset_chat_context())

            restored_messages = json.loads(latest_context.read_text(encoding="utf-8"))

        self.assertEqual(restored_messages, [])
        self.assertEqual(payload["has_action_plan_context"], False)
        self.assertEqual(payload["base_context_version"], "empty")
        self.assertEqual(payload["display_messages"], [])


if __name__ == "__main__":
    unittest.main()

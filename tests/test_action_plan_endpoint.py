import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src import server
from src.services.model_call_recorder import SessionRecorder


class _FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)

    async def readline(self):
        if self._lines:
            return self._lines.pop(0)
        return b""

    async def read(self):
        if not self._lines:
            return b""
        remaining = b"".join(self._lines)
        self._lines.clear()
        return remaining


class _CancelOnReadStdout:
    async def readline(self):
        raise asyncio.CancelledError()


class _FakeProcess:
    def __init__(self, lines=None, returncode=0, stderr_data=b""):
        self.stdout = _FakeStdout(lines or [b'STREAM_ANALYSIS_CONTENT:"ok"\n'])
        stderr_lines = stderr_data.splitlines(keepends=True) if stderr_data else []
        self.stderr = _FakeStdout(stderr_lines)
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
        self.stderr = _FakeStdout([])
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
    def _complete_voice_settings(self):
        return {
            "voice_base_url": "https://voice.example.invalid/v1",
            "voice_api_key": "sk-voice",
            "voice_model": "sensevoice",
        }

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

    def test_chat_endpoint_passes_reasoning_effort_and_client_timestamp_to_subprocess(self):
        fake_process = _FakeProcess(lines=[b'STREAM_CONTENT:"ok"\n'])
        sent_at = "2026-04-08T12:02:03+08:00"

        with patch.object(
            server.asyncio,
            "create_subprocess_exec",
            AsyncMock(return_value=fake_process),
        ) as mock_create:
            response = asyncio.run(
                server.chat_endpoint(
                    server.ChatRequest(
                        message="hello",
                        reasoning_effort="high",
                        client_sent_at=sent_at,
                    ),
                ),
            )
            asyncio.run(_read_first_stream_chunk(response))

        cmd = list(mock_create.await_args.args)
        self.assertIn("--client_sent_at", cmd)
        self.assertIn(sent_at, cmd)
        self.assertEqual(mock_create.await_args.kwargs["env"]["AI_REASONING_EFFORT"], "high")

    def test_chat_endpoint_passes_provider_route_to_subprocess(self):
        fake_process = _FakeProcess(lines=[b'STREAM_CONTENT:"ok"\n'])

        with patch.object(
            server.asyncio,
            "create_subprocess_exec",
            AsyncMock(return_value=fake_process),
        ) as mock_create:
            response = asyncio.run(
                server.chat_endpoint(
                    server.ChatRequest(
                        message="hello",
                        model="gpt-5.5",
                        provider_route="custom",
                    ),
                ),
            )
            asyncio.run(_read_first_stream_chunk(response))

        cmd = list(mock_create.await_args.args)
        self.assertIn("--provider_route", cmd)
        self.assertIn("custom", cmd)

    def test_chat_endpoint_rejects_context_files_outside_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history_dir = Path(temp_dir) / "history"
            history_dir.mkdir()
            outside_context = Path(temp_dir) / "outside.json"

            with patch.object(server.Config, "get_history_dir", return_value=history_dir), patch.object(
                server.asyncio,
                "create_subprocess_exec",
                AsyncMock(),
            ) as mock_create:
                response = asyncio.run(
                    server.chat_endpoint(
                        server.ChatRequest(
                            message="hello",
                            context_file=str(outside_context),
                        ),
                    ),
                )

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "Unsupported chat context file")
        mock_create.assert_not_called()

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
                server,
                "load_settings",
                return_value=self._complete_voice_settings(),
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
                server,
                "load_settings",
                return_value=self._complete_voice_settings(),
            ), patch.object(
                server.asyncio,
                "create_subprocess_exec",
                AsyncMock(return_value=fake_process),
            ):
                with self.assertRaises(RuntimeError):
                    asyncio.run(server.transcribe_audio(_FakeUploadFile()))

            self.assertFalse(expected_temp_file.exists())

    def test_transcribe_audio_uses_unique_temp_files_for_same_second_uploads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_abspath = server.os.path.abspath
            temp_paths = []

            def fake_abspath(path):
                if path == server.__file__:
                    return os.path.join(temp_dir, "src", "server.py")
                return original_abspath(path)

            async def fake_create_subprocess_exec(*cmd, **kwargs):
                temp_paths.append(Path(cmd[cmd.index("--transcribe") + 1]))
                return _FakeProcess(returncode=0)

            with patch.object(server.time, "time", return_value=1234567892), patch.object(
                server.os.path,
                "abspath",
                side_effect=fake_abspath,
            ), patch.object(
                server,
                "load_settings",
                return_value=self._complete_voice_settings(),
            ), patch.object(
                server.asyncio,
                "create_subprocess_exec",
                AsyncMock(side_effect=fake_create_subprocess_exec),
            ):
                asyncio.run(server.transcribe_audio(_FakeUploadFile()))
                asyncio.run(server.transcribe_audio(_FakeUploadFile()))

            self.assertEqual(len(temp_paths), 2)
            self.assertEqual(len(set(temp_paths)), 2)
            self.assertTrue(all(path.parent == Path(temp_dir) for path in temp_paths))
            self.assertFalse(any(path.exists() for path in temp_paths))

    def test_transcribe_audio_returns_configuration_error_when_voice_provider_missing(self):
        with patch.object(
            server,
            "load_settings",
            return_value={
                "voice_base_url": "",
                "voice_api_key": "",
                "voice_model": "FunAudioLLM/SenseVoiceSmall",
            },
        ), patch.object(
            server.asyncio,
            "create_subprocess_exec",
            AsyncMock(),
        ) as mock_create:
            response = asyncio.run(server.transcribe_audio(_FakeUploadFile()))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "Voice transcription provider is not configured")
        self.assertEqual(payload["voice_model"], "FunAudioLLM/SenseVoiceSmall")
        self.assertEqual(payload["voice_base_url"], "")
        self.assertEqual(payload["configuration_error"], True)
        self.assertEqual(payload["missing"], ["voice_base_url", "voice_api_key"])
        mock_create.assert_not_called()

    def test_transcribe_audio_passes_voice_provider_to_run_prompt_and_returns_metadata(self):
        fake_process = _FakeProcess(returncode=0)
        fake_process.communicate = AsyncMock(return_value=(b"TRANSCRIPTION_RESULT:hello\n", b""))
        created_args = []
        created_env = {}

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            created_args.extend(cmd)
            created_env.update(kwargs.get("env") or {})
            return fake_process

        with patch.object(server, "load_settings", return_value=self._complete_voice_settings()), patch.object(
            server.asyncio,
            "create_subprocess_exec",
            AsyncMock(side_effect=fake_create_subprocess_exec),
        ):
            response = asyncio.run(server.transcribe_audio(_FakeUploadFile()))

        self.assertEqual(response["transcription"], "hello")
        self.assertEqual(response["voice_model"], "sensevoice")
        self.assertEqual(response["voice_base_url"], "https://voice.example.invalid/v1")
        self.assertIn("--transcribe-base-url", created_args)
        self.assertIn("--transcribe-model", created_args)
        self.assertNotIn("--transcribe-api-key", created_args)
        self.assertEqual(created_args[created_args.index("--transcribe-base-url") + 1], "https://voice.example.invalid/v1")
        self.assertEqual(created_args[created_args.index("--transcribe-model") + 1], "sensevoice")
        self.assertEqual(created_env["VANTAGE_TRANSCRIBE_API_KEY"], "sk-voice")

    def test_transcribe_audio_redacts_voice_api_key_from_logs(self):
        fake_process = _FakeProcess(returncode=0)
        fake_process.communicate = AsyncMock(return_value=(b"TRANSCRIPTION_RESULT:hello\n", b""))
        created_args = []
        created_env = {}

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            created_args.extend(cmd)
            created_env.update(kwargs.get("env") or {})
            return fake_process

        with patch.object(server, "load_settings", return_value=self._complete_voice_settings()), patch.object(
            server.asyncio,
            "create_subprocess_exec",
            AsyncMock(side_effect=fake_create_subprocess_exec),
        ), patch("builtins.print") as mock_print:
            response = asyncio.run(server.transcribe_audio(_FakeUploadFile()))

        self.assertEqual(response["transcription"], "hello")
        self.assertNotIn("--transcribe-api-key", created_args)
        self.assertEqual(created_env["VANTAGE_TRANSCRIBE_API_KEY"], "sk-voice")
        printed = "\n".join(" ".join(str(arg) for arg in call.args) for call in mock_print.call_args_list)
        self.assertNotIn("sk-voice", printed)
        self.assertNotIn("--transcribe-api-key", printed)
        self.assertNotIn("TRANSCRIPTION_RESULT:hello", printed)
        self.assertNotIn("Result: 'hello'", printed)

    def test_transcribe_audio_returns_error_when_subprocess_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_abspath = server.os.path.abspath

            def fake_abspath(path):
                if path == server.__file__:
                    return os.path.join(temp_dir, "src", "server.py")
                return original_abspath(path)

            fake_process = _FakeProcess(returncode=1, stderr_data=b"transcribe failed")
            fake_process.communicate = AsyncMock(return_value=(b"TRANSCRIPTION_ERROR:missing api key\n", b"transcribe failed"))

            with patch.object(server.os.path, "abspath", side_effect=fake_abspath), patch.object(
                server,
                "load_settings",
                return_value=self._complete_voice_settings(),
            ), patch.object(
                server.asyncio,
                "create_subprocess_exec",
                AsyncMock(return_value=fake_process),
            ):
                response = asyncio.run(server.transcribe_audio(_FakeUploadFile()))

            self.assertEqual(response.status_code, 500)
            payload = json.loads(response.body.decode("utf-8"))
            self.assertEqual(payload["error"], "Transcription failed")
            self.assertIn("missing api key", payload["details"])

    def test_transcribe_audio_redacts_voice_api_key_from_error_details(self):
        fake_process = _FakeProcess(returncode=1)
        fake_process.communicate = AsyncMock(return_value=(b"TRANSCRIPTION_ERROR:bad key sk-voice\n", b""))

        with patch.object(server, "load_settings", return_value=self._complete_voice_settings()), patch.object(
            server.asyncio,
            "create_subprocess_exec",
            AsyncMock(return_value=fake_process),
        ):
            response = asyncio.run(server.transcribe_audio(_FakeUploadFile()))

        self.assertEqual(response.status_code, 500)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertNotIn("sk-voice", payload["details"])
        self.assertIn("[REDACTED_API_KEY]", payload["details"])

    def test_generate_action_plan_replace_today_deletes_older_today_files_after_success(self):
        today = datetime.now().strftime("%Y%m%d")

        with tempfile.TemporaryDirectory() as temp_dir:
            history_dir = Path(temp_dir) / "history"
            history_dir.mkdir()

            old_file_a = history_dir / f"action_plan_{today}_010101.json"
            old_file_b = history_dir / f"action_plan_{today}_020202.json"
            new_file = history_dir / f"action_plan_{today}_030303.json"
            old_file_a.write_text("old a", encoding="utf-8")
            old_file_b.write_text("old b", encoding="utf-8")

            async def fake_create_subprocess_exec(*args, **kwargs):
                new_file.write_text("new", encoding="utf-8")
                return _FakeProcess(returncode=0)

            with patch.object(server.Config, "get_history_dir", return_value=history_dir), patch.object(
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

            old_file_a = history_dir / f"action_plan_{today}_010101.json"
            old_file_b = history_dir / f"action_plan_{today}_020202.json"
            old_file_a.write_text("old a", encoding="utf-8")
            old_file_b.write_text("old b", encoding="utf-8")

            with patch.object(server.Config, "get_history_dir", return_value=history_dir), patch.object(
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

    def test_get_today_action_plan_returns_structured_json_payload(self):
        today = datetime.now().strftime("%Y%m%d")

        with tempfile.TemporaryDirectory() as temp_dir:
            history_dir = Path(temp_dir) / "history"
            history_dir.mkdir()
            latest_file = history_dir / f"action_plan_{today}_112348.json"
            latest_file.write_text(
                json.dumps(
                    {
                        "id": f"{today}_112348",
                        "date": "2026-04-14",
                        "analysis": {"body": "analysis markdown"},
                        "plan": {"body": "plan markdown"},
                        "meta": {"generated_at": "2026-04-14T11:23:48+08:00"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(server.Config, "get_history_dir", return_value=history_dir):
                payload = asyncio.run(server.get_today_action_plan())

        self.assertEqual(payload["exists"], True)
        self.assertEqual(payload["analysis"]["body"], "analysis markdown")
        self.assertEqual(payload["plan"]["body"], "plan markdown")
        self.assertEqual(payload["filename"], latest_file.name)

    def test_get_today_action_plan_hydrates_legacy_input_from_action_plan_context(self):
        today = datetime.now().strftime("%Y%m%d")

        with tempfile.TemporaryDirectory() as temp_dir:
            history_dir = Path(temp_dir) / "history"
            history_dir.mkdir()
            latest_file = history_dir / f"action_plan_{today}_112348.json"
            latest_file.write_text(
                json.dumps(
                    {
                        "id": f"{today}_112348",
                        "date": "2026-04-14",
                        "analysis": {"body": "analysis markdown"},
                        "plan": {"body": "plan markdown"},
                        "meta": {"generated_at": "2026-04-14T11:23:48+08:00"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (history_dir / "latest_action_plan_context.json").write_text(
                json.dumps(
                    [
                        {"role": "system", "content": "system prompt"},
                        {"role": "user", "content": "analysis prompt"},
                        {"role": "assistant", "content": "analysis markdown"},
                        {"role": "user", "content": "plan prompt"},
                        {"role": "assistant", "content": "plan markdown"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(server.Config, "get_history_dir", return_value=history_dir):
                payload = asyncio.run(server.get_today_action_plan())

        self.assertEqual(
            payload["meta"]["input"],
            {
                "system_prompt": "system prompt",
                "analysis_prompt": "analysis prompt",
                "plan_prompt": "plan prompt",
            },
        )

    def test_get_usage_dashboard_returns_aggregated_history_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history_dir = Path(temp_dir) / "history"
            recorder = SessionRecorder(
                session_id="usage-session-1",
                source="chat",
                entrypoint="src/scripts/run_prompt.py",
                history_dir=history_dir,
                default_model="gpt-5.4",
                provider_route="cliproxyapi_primary",
                base_url="http://127.0.0.1:8317/v1",
                created_at=datetime.fromisoformat("2026-04-18T20:00:00+08:00"),
            )
            with patch(
                "src.services.model_call_recorder._now",
                return_value=datetime.fromisoformat("2026-04-18T20:05:00+08:00"),
            ):
                recorder.record_request_started(
                    call_id="usage-call-1",
                    model="gpt-5.4",
                    provider_route="cliproxyapi_primary",
                    stream=False,
                    reasoning_effort="medium",
                    messages=[{"role": "user", "content": "hello"}],
                )
                recorder.record_request_completed(
                    call_id="usage-call-1",
                    model="gpt-5.4",
                    provider_route="cliproxyapi_primary",
                    stream=False,
                    reasoning_effort="medium",
                    content="world",
                    thinking="",
                    usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                    duration=4.0,
                )

            with patch.object(server.Config, "get_history_dir", return_value=history_dir):
                payload = asyncio.run(server.get_usage_dashboard())

        self.assertEqual(payload["summary"]["session_count"], 1)
        self.assertEqual(payload["summary"]["completed_call_count"], 1)
        self.assertEqual(payload["summary"]["failed_call_count"], 0)
        self.assertEqual(payload["summary"]["total_tokens"], 120)
        self.assertEqual(payload["by_source"][0]["source"], "chat")
        self.assertEqual(payload["by_source"][0]["total_tokens"], 120)
        self.assertEqual(payload["sessions"][0]["session_id"], "usage-session-1")
        self.assertEqual(payload["recent_calls"][0]["call_id"], "usage-call-1")

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

    def test_generate_action_plan_accepts_max_reasoning_effort(self):
        fake_process = _FakeProcess()

        with patch.object(
            server.asyncio,
            "create_subprocess_exec",
            AsyncMock(return_value=fake_process),
        ) as mock_create:
            response = asyncio.run(
                server.generate_action_plan(
                    server.ActionPlanRequest(reasoning_effort="max"),
                ),
            )
            asyncio.run(_read_first_stream_chunk(response))

        self.assertEqual(mock_create.await_args.kwargs["env"]["AI_REASONING_EFFORT"], "max")

    def test_generate_action_plan_passes_provider_route_to_subprocess(self):
        fake_process = _FakeProcess()

        with patch.object(
            server.asyncio,
            "create_subprocess_exec",
            AsyncMock(return_value=fake_process),
        ) as mock_create:
            response = asyncio.run(
                server.generate_action_plan(
                    server.ActionPlanRequest(model="gpt-5.5", provider_route="custom"),
                ),
            )
            asyncio.run(_read_first_stream_chunk(response))

        cmd = list(mock_create.await_args.args)
        self.assertIn("--provider_route=custom", cmd)

    def test_generate_action_plan_passes_priority_service_tier_to_subprocess(self):
        fake_process = _FakeProcess()

        with patch.object(
            server.asyncio,
            "create_subprocess_exec",
            AsyncMock(return_value=fake_process),
        ) as mock_create:
            response = asyncio.run(
                server.generate_action_plan(
                    server.ActionPlanRequest(
                        model="gpt-5.5",
                        provider_route="custom",
                        service_tier="priority",
                    ),
                ),
            )
            asyncio.run(_read_first_stream_chunk(response))

        cmd = list(mock_create.await_args.args)
        self.assertIn("--service_tier=priority", cmd)
        self.assertEqual(mock_create.await_args.kwargs["env"]["AI_SERVICE_TIER"], "priority")

    def test_list_llm_models_includes_provider_aware_options(self):
        fake_client = unittest.mock.Mock()
        fake_client.get_model_catalog.return_value = [
            {
                "route": "custom",
                "name": "Custom",
                "model": "gpt-5.5",
                "models": ["gpt-5.5", "gpt-5.4"],
                "base_url": "http://127.0.0.1:8317/v1",
                "model_capabilities": {},
            },
            {
                "route": "cloud",
                "name": "Cloud",
                "model": "gpt-5.5",
                "models": ["gpt-5.5"],
                "base_url": "https://cloud.invalid/v1",
                "model_capabilities": {},
            },
        ]

        with patch.object(server, "LLMClient", return_value=fake_client):
            payload = asyncio.run(server.list_llm_models())

        self.assertEqual(payload["models"], ["gpt-5.5", "gpt-5.4"])
        self.assertEqual(payload["default_model"], "gpt-5.5")
        self.assertEqual(
            [option["id"] for option in payload["model_options"]],
            ["custom::gpt-5.5", "custom::gpt-5.4", "cloud::gpt-5.5"],
        )
        self.assertEqual(payload["model_options"][0]["provider_route"], "custom")

    def test_discover_llm_models_redacts_api_key_from_errors(self):
        request = server.LLMModelDiscoverRequest(
            route="custom",
            base_url="http://127.0.0.1:8317/v1",
            api_key="sk-test-secret-1234567890",
            type="openai-compatible",
        )

        with patch.object(
            server.LLMClient,
            "discover_models_for_config",
            side_effect=RuntimeError("bad key sk-test-secret-1234567890"),
        ):
            response = asyncio.run(server.discover_llm_models(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("sk-test-secret-1234567890", payload["error"])
        self.assertIn("[REDACTED_API_KEY]", payload["error"])

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

    def test_generate_action_plan_logs_stderr_fallback_lines_to_server_log(self):
        fake_process = _FakeProcess(
            lines=[b'STREAM_ANALYSIS_CONTENT:"ok"\n'],
            returncode=0,
            stderr_data=(
                b"2026-03-08 14:58:33 - WARNING - LLM route cliproxyapi_primary failed for model gpt-5.2 at http://127.0.0.1:8317/v1: timeout\n"
                b"2026-03-08 14:58:34 - INFO - LLM route cliproxyapi_secondary succeeded with model gemini-3.1-pro-high at http://127.0.0.1:8045/v1\n"
            ),
        )

        with patch.object(
            server.asyncio,
            "create_subprocess_exec",
            AsyncMock(return_value=fake_process),
        ), patch.object(server.logging, "warning") as mock_warning, patch.object(
            server.logging,
            "info",
        ) as mock_info:
            response = asyncio.run(server.generate_action_plan())
            chunks = asyncio.run(_read_all_stream_chunks(response))

        combined = "".join(chunks)
        self.assertIn('STREAM_ANALYSIS_CONTENT', combined)
        self.assertNotIn('cliproxyapi_primary failed', combined)
        self.assertTrue(any(
            "cliproxyapi_primary failed" in call.args[0]
            for call in mock_warning.call_args_list
        ))
        self.assertTrue(any(
            "cliproxyapi_secondary succeeded" in call.args[0]
            for call in mock_info.call_args_list
        ))

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

    def test_generate_action_plan_uses_packaged_run_prompt_bridge_when_frozen(self):
        fake_process = _FakeProcess(lines=[b'STREAM_ANALYSIS_CONTENT:"ok"\n'])
        executable_path = r"C:\Program Files\Vantage\VantageBackend.exe"
        runtime_root = Path(r"C:\Program Files\Vantage\resources\backend-runtime\VantageBackend\_internal")

        with patch.object(server.sys, "frozen", True, create=True), patch.object(
            server.sys,
            "executable",
            executable_path,
        ), patch.object(
            server.Config,
            "get_project_root",
            return_value=runtime_root,
        ), patch.object(
            server.asyncio,
            "create_subprocess_exec",
            AsyncMock(return_value=fake_process),
        ) as mock_create:
            response = asyncio.run(
                server.generate_action_plan(
                    server.ActionPlanRequest(
                        model="gpt-5.3-codex-spark",
                        reasoning_effort="high",
                    ),
                ),
            )
            asyncio.run(_read_all_stream_chunks(response))

        cmd = list(mock_create.await_args.args)
        self.assertEqual(
            cmd,
            [
                executable_path,
                "--run-prompt",
                "--model=gpt-5.3-codex-spark",
            ],
        )
        self.assertEqual(mock_create.await_args.kwargs["cwd"], str(runtime_root))

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

            with patch.object(server.Config, "get_history_dir", return_value=history_dir):
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

    def test_get_chat_context_includes_active_session_stats(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history_dir = Path(temp_dir) / "history"
            history_dir.mkdir()
            base_context = history_dir / "latest_action_plan_context.json"
            base_context.write_text(
                json.dumps(
                    [
                        {"role": "assistant", "content": "analysis result"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            latest_context_session = history_dir / "latest_context_session.json"
            latest_context_session.write_text(
                json.dumps({"session_id": "session-chat-1"}, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(server.Config, "get_history_dir", return_value=history_dir), patch.object(
                server,
                "get_session_usage_summary",
                return_value={
                    "session_id": "session-chat-1",
                    "call_count": 3,
                    "prompt_tokens": 30,
                    "completion_tokens": 11,
                    "total_tokens": 41,
                    "total_duration": 9.2,
                    "average_duration": 3.06,
                },
            ):
                payload = asyncio.run(server.get_chat_context())

        self.assertEqual(payload["stats"]["session_id"], "session-chat-1")
        self.assertEqual(payload["stats"]["total_tokens"], 41)
        self.assertEqual(payload["stats"]["call_count"], 3)

    def test_get_chat_context_reports_preferred_action_plan_model_route(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history_dir = Path(temp_dir) / "history"
            history_dir.mkdir()
            (history_dir / "latest_action_plan_context.json").write_text(
                json.dumps([{"role": "assistant", "content": "plan result"}], ensure_ascii=False),
                encoding="utf-8",
            )
            (history_dir / "latest_context_session.json").write_text(
                json.dumps(
                    {
                        "session_id": "session-action-1",
                        "source": "action_plan",
                        "model": "deepseek-v4-flash",
                        "provider_route": "deepseek",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(server.Config, "get_history_dir", return_value=history_dir):
                payload = asyncio.run(server.get_chat_context())

        self.assertEqual(payload["preferred_model"], "deepseek-v4-flash")
        self.assertEqual(payload["preferred_provider_route"], "deepseek")
        self.assertEqual(payload["preferred_model_option_id"], "deepseek::deepseek-v4-flash")

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

            with patch.object(server.Config, "get_history_dir", return_value=history_dir):
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

            with patch.object(server.Config, "get_history_dir", return_value=history_dir):
                payload = asyncio.run(server.reset_chat_context())

            restored_messages = json.loads(latest_context.read_text(encoding="utf-8"))

        self.assertEqual(restored_messages, [])
        self.assertEqual(payload["has_action_plan_context"], False)
        self.assertEqual(payload["base_context_version"], "empty")
        self.assertEqual(payload["display_messages"], [])

    def test_reset_chat_context_restores_action_plan_session_sidecar(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history_dir = Path(temp_dir) / "history"
            history_dir.mkdir()
            latest_context = history_dir / "latest_context.json"
            latest_context.write_text(
                json.dumps([{"role": "user", "content": "stale chat"}], ensure_ascii=False),
                encoding="utf-8",
            )
            (history_dir / "latest_context_session.json").write_text(
                json.dumps({"session_id": "chat-session"}, ensure_ascii=False),
                encoding="utf-8",
            )
            (history_dir / "latest_action_plan_context.json").write_text(
                json.dumps([{"role": "assistant", "content": "seed plan"}], ensure_ascii=False),
                encoding="utf-8",
            )
            (history_dir / "latest_action_plan_context_session.json").write_text(
                json.dumps({"session_id": "action-plan-session"}, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(server.Config, "get_history_dir", return_value=history_dir):
                asyncio.run(server.reset_chat_context())

            restored_session_payload = json.loads(
                (history_dir / "latest_context_session.json").read_text(encoding="utf-8")
            )

        self.assertEqual(restored_session_payload["session_id"], "action-plan-session")


if __name__ == "__main__":
    unittest.main()

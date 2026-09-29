import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.scripts import verify_backend_runtime


FACE_PREWARM_SUCCESS = "Camera face detector warmed up successfully."
CURRENT_LAUNCH_BANNER = "=== Background server launch 2026-07-15T10:00:00 ==="


def _write_runtime_log(smoke_data_dir: Path, text: str) -> Path:
    log_path = smoke_data_dir / "logs" / "server" / "server-current.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(text, encoding="utf-8")
    pointer_path = smoke_data_dir / "logs" / "server.latest.log"
    pointer_path.write_text(str(log_path.resolve()), encoding="utf-8")
    return log_path.resolve()


class VerifyBackendRuntimeTests(unittest.TestCase):
    def test_packaged_cli_smoke_uses_backend_executable_and_parses_json_stdout(self):
        executable = Path("runtime/VantageBackend.exe")
        expected = {"status": "ready"}
        completed = SimpleNamespace(returncode=0, stdout='{"status":"ready"}\n', stderr="")

        with patch.object(verify_backend_runtime.subprocess, "run", return_value=completed) as run:
            result = verify_backend_runtime._run_packaged_cli_smoke(
                executable,
                cwd=Path("runtime"),
                env={"VANTAGE_APP_MODE": "packaged"},
            )

        self.assertEqual(result, expected)
        self.assertEqual(
            run.call_args.args[0],
            [
                str(executable),
                "--run-cli",
                "--format",
                "json",
                "system",
                "status",
                "read",
            ],
        )
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertEqual(run.call_args.kwargs["cwd"], "runtime")

    def test_packaged_mcp_smoke_uses_stdio_client_and_checks_catalog_operation(self):
        parameters_seen = []

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def list_tools(self):
                return SimpleNamespace(tools=[SimpleNamespace(name="system.status.read")])

            async def call_tool(self, _name, _arguments):
                return SimpleNamespace(is_error=False, structured_content={"status": "ready"})

        with patch("mcp.Client", side_effect=lambda _parameters: FakeClient()) as client_factory, patch(
            "mcp.client.stdio.StdioServerParameters",
            side_effect=lambda **kwargs: parameters_seen.append(kwargs) or kwargs,
        ):
            result = verify_backend_runtime._run_packaged_mcp_smoke(
                Path("runtime/VantageBackend.exe"),
                cwd=Path("runtime"),
                env={"VANTAGE_APP_MODE": "packaged"},
            )

        self.assertEqual(result["tool_count"], 1)
        self.assertEqual(result["status"], {"status": "ready"})
        self.assertEqual(parameters_seen[0]["args"], ["--run-cli", "mcp"])
        self.assertEqual(
            parameters_seen[0]["command"], str(Path("runtime/VantageBackend.exe"))
        )
        client_factory.assert_called_once()

    def test_build_smoke_environment_pins_media_paths_into_smoke_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            layout = {
                "build_root": tmp_path / "build",
                "runtime_dir": tmp_path / "stage" / "VantageBackend",
                "resource_dir": tmp_path / "stage" / "VantageBackend" / "_internal",
            }

            layout["resource_dir"].mkdir(parents=True, exist_ok=True)

            env = verify_backend_runtime._build_smoke_environment(layout)

            config_dir = Path(env["VANTAGE_CONFIG_DIR"])
            settings_file = config_dir / "media-paths.json"
            payload = json.loads(settings_file.read_text(encoding="utf-8"))

            self.assertEqual(config_dir, layout["build_root"] / "smoke-data" / "config")
            self.assertEqual(Path(payload["photos_path"]), layout["build_root"] / "smoke-data" / "photos")
            self.assertEqual(
                Path(payload["screenshots_path"]),
                layout["build_root"] / "smoke-data" / "screenshots",
            )
            self.assertEqual(env["VANTAGE_DATA_DIR"], str(layout["build_root"] / "smoke-data"))
            self.assertEqual(env["VANTAGE_MACOS_SKIP_CAMERA_AUTH"], "1")
            self.assertEqual(env["OPENCV_AVFOUNDATION_SKIP_AUTH"], "1")
            self.assertEqual(env["VANTAGE_PREWARM_FACE_DETECTION_ON_STARTUP"], "1")

    def test_build_smoke_environment_removes_host_model_overrides(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            layout = {
                "build_root": tmp_path / "build",
                "runtime_dir": tmp_path / "stage" / "VantageBackend",
                "resource_dir": tmp_path / "stage" / "VantageBackend" / "_internal",
            }
            layout["resource_dir"].mkdir(parents=True, exist_ok=True)
            host_path = str(tmp_path / "host-runtime-bin")

            with patch.dict(
                os.environ,
                {
                    "PATH": host_path,
                    "VANTAGE_FACE_DETECTION_MODEL_PATH": str(
                        tmp_path / "external-face.onnx"
                    ),
                    "VANTAGE_PERSON_PRESENCE_MODEL_PATH": "unused-legacy-value",
                    "VANTAGE_PROJECT_ROOT": str(tmp_path / "external-project"),
                },
                clear=False,
            ):
                env = verify_backend_runtime._build_smoke_environment(layout)

            self.assertNotIn("VANTAGE_FACE_DETECTION_MODEL_PATH", env)
            self.assertEqual(
                env["VANTAGE_PERSON_PRESENCE_MODEL_PATH"], "unused-legacy-value"
            )
            self.assertNotIn("VANTAGE_PROJECT_ROOT", env)
            self.assertIn(host_path, env["PATH"].split(os.pathsep))

    def test_status_payload_must_match_current_runtime_layout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            layout = {
                "resource_dir": tmp_path / "stage" / "VantageBackend" / "_internal",
            }

            self.assertTrue(
                verify_backend_runtime._status_matches_runtime_layout(
                    {"runtime": {"cwd_name": "_internal"}},
                    layout,
                )
            )
            self.assertFalse(
                verify_backend_runtime._status_matches_runtime_layout(
                    {"runtime": {"cwd_name": "other-runtime"}},
                    layout,
                )
            )

    def test_find_runtime_blockers_flags_packaged_dll_errors(self):
        log_text = "\n".join(
            [
                "Face detector unavailable in thread: DLL load failed while loading opencv_world.dll",
                "Face detector unavailable in thread: No module named 'cv2'",
                "Camera face detector unavailable in thread: Missing face detection model",
                "Live face analysis error: DLL load failed while importing _framework_bindings",
                "Missing packaged runtime module(s): zhdate (No module named 'zhdate')",
                "Failed to warm camera face detector: invalid YuNet model",
                "Failed to warm camera body detector: legacy detector failure",
            ]
        )

        blockers = verify_backend_runtime._find_runtime_blockers(log_text)

        self.assertEqual(
            blockers,
            [
                "DLL load failed",
                "Live face analysis error",
                "Missing packaged runtime module",
                "No module named",
                "Missing face detection model",
                "Failed to warm camera face detector",
            ],
        )

    def test_runtime_log_resolution_rejects_target_outside_smoke_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            smoke_data_dir = tmp_path / "smoke-data"
            outside_log = tmp_path / "unrelated-server.log"
            outside_log.write_text(
                f"{FACE_PREWARM_SUCCESS}\n",
                encoding="utf-8",
            )
            pointer = smoke_data_dir / "logs" / "server.latest.log"
            pointer.parent.mkdir(parents=True, exist_ok=True)
            pointer.write_text(str(outside_log.resolve()), encoding="utf-8")

            self.assertIsNone(
                verify_backend_runtime._resolve_runtime_server_log(smoke_data_dir)
            )

    def test_runtime_log_resolution_rejects_non_server_log_inside_smoke_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            smoke_data_dir = Path(tmpdir) / "smoke-data"
            unrelated_log = smoke_data_dir / "logs" / "unrelated.log"
            unrelated_log.parent.mkdir(parents=True, exist_ok=True)
            unrelated_log.write_text(
                f"{FACE_PREWARM_SUCCESS}\n",
                encoding="utf-8",
            )
            pointer = smoke_data_dir / "logs" / "server.latest.log"
            pointer.write_text(str(unrelated_log.resolve()), encoding="utf-8")

            self.assertIsNone(
                verify_backend_runtime._resolve_runtime_server_log(smoke_data_dir)
            )

    def test_runtime_log_pointer_reset_removes_previous_launch_pointer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            smoke_data_dir = Path(tmpdir) / "smoke-data"
            pointer = smoke_data_dir / "logs" / "server.latest.log"
            pointer.parent.mkdir(parents=True, exist_ok=True)
            pointer.write_text("stale log pointer", encoding="utf-8")

            verify_backend_runtime._clear_runtime_server_log_pointer(
                smoke_data_dir
            )

            self.assertFalse(pointer.exists())

    def test_runtime_log_validation_fails_when_pointer_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            smoke_data_dir = Path(tmpdir) / "smoke-data"

            log_path, log_text, errors = (
                verify_backend_runtime._read_verified_runtime_server_log(
                    smoke_data_dir
                )
            )

            self.assertIsNone(log_path)
            self.assertEqual(log_text, "")
            self.assertTrue(any("missing or invalid" in error for error in errors))

    def test_runtime_log_validation_fails_when_target_is_unreadable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_log = Path(tmpdir) / "smoke-data" / "logs" / "server" / "server.log"
            with (
                patch.object(
                    verify_backend_runtime,
                    "_resolve_runtime_server_log",
                    return_value=runtime_log,
                ),
                patch.object(Path, "read_text", side_effect=PermissionError("denied")),
            ):
                log_path, log_text, errors = (
                    verify_backend_runtime._read_verified_runtime_server_log(
                        Path(tmpdir) / "smoke-data"
                    )
                )

            self.assertEqual(log_path, runtime_log)
            self.assertEqual(log_text, "")
            self.assertTrue(any("unreadable" in error for error in errors))

    def test_runtime_log_tail_is_empty_when_log_is_unreadable(self):
        unreadable_log = Path("unreadable-runtime.log")
        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", side_effect=PermissionError("denied")),
        ):
            self.assertEqual(
                verify_backend_runtime._tail_text_file(unreadable_log),
                "",
            )

    def test_runtime_log_validation_fails_when_log_is_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            smoke_data_dir = Path(tmpdir) / "smoke-data"
            runtime_log = _write_runtime_log(smoke_data_dir, "")

            log_path, log_text, errors = (
                verify_backend_runtime._read_verified_runtime_server_log(
                    smoke_data_dir
                )
            )

            self.assertEqual(log_path, runtime_log)
            self.assertEqual(log_text, "")
            self.assertTrue(any("empty" in error for error in errors))

    def test_runtime_log_validation_requires_face_prewarm_success_marker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            smoke_data_dir = Path(tmpdir) / "smoke-data"
            _write_runtime_log(
                smoke_data_dir,
                f"{CURRENT_LAUNCH_BANNER}\n",
            )

            _, _, errors = verify_backend_runtime._read_verified_runtime_server_log(
                smoke_data_dir
            )

            self.assertTrue(any(FACE_PREWARM_SUCCESS in error for error in errors))

    def test_runtime_log_validation_ignores_success_markers_before_current_launch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            smoke_data_dir = Path(tmpdir) / "smoke-data"
            _write_runtime_log(
                smoke_data_dir,
                "\n".join(
                    [
                        "=== Background server launch old ===",
                        FACE_PREWARM_SUCCESS,
                        CURRENT_LAUNCH_BANNER,
                        "",
                    ]
                ),
            )

            _, current_log_text, errors = (
                verify_backend_runtime._read_verified_runtime_server_log(
                    smoke_data_dir
                )
            )

            self.assertTrue(current_log_text.startswith(CURRENT_LAUNCH_BANNER))
            self.assertTrue(any(FACE_PREWARM_SUCCESS in error for error in errors))

    def test_runtime_log_validation_accepts_current_complete_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            smoke_data_dir = Path(tmpdir) / "smoke-data"
            expected_text = (
                f"{CURRENT_LAUNCH_BANNER}\n"
                f"{FACE_PREWARM_SUCCESS}\n"
            )
            runtime_log = _write_runtime_log(smoke_data_dir, expected_text)

            log_path, log_text, errors = (
                verify_backend_runtime._read_verified_runtime_server_log(
                    smoke_data_dir
                )
            )

            self.assertEqual(log_path, runtime_log)
            self.assertEqual(log_text, expected_text)
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()

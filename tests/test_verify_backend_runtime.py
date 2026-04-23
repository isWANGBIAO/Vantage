import json
import tempfile
import unittest
from pathlib import Path

from src.scripts import verify_backend_runtime


class VerifyBackendRuntimeTests(unittest.TestCase):
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

    def test_status_payload_must_match_current_runtime_layout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            layout = {
                "resource_dir": tmp_path / "stage" / "VantageBackend" / "_internal",
            }

            self.assertTrue(
                verify_backend_runtime._status_matches_runtime_layout(
                    {"cwd": str(layout["resource_dir"])},
                    layout,
                )
            )
            self.assertFalse(
                verify_backend_runtime._status_matches_runtime_layout(
                    {"cwd": str(tmp_path / "other-runtime")},
                    layout,
                )
            )

    def test_find_runtime_blockers_flags_packaged_dll_errors(self):
        log_text = "\n".join(
            [
                "Failed to load YOLO model in thread: [WinError 1114] Error loading c10.dll",
                "Live face analysis error: DLL load failed while importing _framework_bindings",
            ]
        )

        blockers = verify_backend_runtime._find_runtime_blockers(log_text)

        self.assertEqual(
            blockers,
            [
                "Failed to load YOLO model",
                "c10.dll",
                "DLL load failed",
                "Live face analysis error",
            ],
        )


if __name__ == "__main__":
    unittest.main()

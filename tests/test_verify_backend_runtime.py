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
                "resource_dir": tmp_path / "stage" / "VantageBackend" / "_internal",
            }

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


if __name__ == "__main__":
    unittest.main()

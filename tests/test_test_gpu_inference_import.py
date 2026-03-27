import subprocess
import sys
import tempfile
from pathlib import Path


def test_importing_gpu_inference_script_does_not_create_output_file():
    script_path = Path("src/scripts/test_gpu_inference.py").resolve()

    with tempfile.TemporaryDirectory() as tmp_dir:
        subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import importlib.util; "
                    f"spec = importlib.util.spec_from_file_location('gpu_diag_module', r'{script_path}'); "
                    "module = importlib.util.module_from_spec(spec); "
                    "spec.loader.exec_module(module)"
                ),
            ],
            cwd=tmp_dir,
            timeout=30,
            check=True,
        )

        assert not Path(tmp_dir, "gpu_diag_output.txt").exists()

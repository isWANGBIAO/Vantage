from pathlib import Path

import pytest

from scripts.build_native_backend import build_commands, main


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_native_clients_reuse_validated_backend_pipeline(platform):
    root = Path("/fixture/Vantage")
    commands = build_commands(root, platform, "bootstrap-python", 123)
    assert "sync_backend_runtime_environment.py" in commands[0][1]
    assert "requirements-core.txt" in commands[0][-5]
    assert "requirements-backend-runtime-gpu.txt" in commands[0][-3]
    assert commands[1][1:] == ["-m", "pip", "check"]
    assert str(root / ".venv-backend-runtime-gpu") in commands[-1][0]
    assert commands[-2][-1] == "--reuse-if-unchanged"
    assert commands[-1][1:] == [str(root / "src/scripts/verify_backend_runtime.py"), "--timeout-seconds", "123", "--isolated"]
    assert not any("--skip-launch" in item for command in commands for item in command)
    signers = [command for command in commands if "sign_macos_backend_runtime.py" in " ".join(command)]
    assert len(signers) == (1 if platform == "darwin" else 0)


@pytest.mark.parametrize("timeout", ["0", "-1", "601"])
def test_bad_timeout_fails_before_running_commands(timeout):
    with pytest.raises(SystemExit):
        main(["--timeout-seconds", timeout])

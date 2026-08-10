import sys
from pathlib import Path
from types import SimpleNamespace

from src.scripts import normalize_opencv_installation as opencv_normalizer


OPENCV_DISTRIBUTIONS = (
    "opencv-contrib-python",
    "opencv-contrib-python-headless",
    "opencv-python",
    "opencv-python-headless",
)


def _write_core(tmp_path, requirement="opencv-contrib-python==4.14.0.94"):
    core_path = tmp_path / "requirements-core.txt"
    core_path.write_text(f"{requirement}\n", encoding="utf-8")
    return core_path


def test_target_contract_is_read_from_shared_core():
    target = opencv_normalizer.read_target_contract(Path("requirements-core.txt"))

    assert target.distribution == "opencv-contrib-python"
    assert target.wheel_version == "4.14.0.94"
    assert target.cv2_version == "4.14.0"
    assert opencv_normalizer.OPENCV_DISTRIBUTIONS == OPENCV_DISTRIBUTIONS


def test_clean_installation_skips_destructive_reconciliation(tmp_path):
    core_path = _write_core(tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="4.14.0\n", stderr="")

    result = opencv_normalizer.normalize_opencv_installation(
        core_path,
        get_installed_distributions=lambda: {
            "opencv-contrib-python": "4.14.0.94"
        },
        run_command=fake_run,
        python_executable=sys.executable,
    )

    assert result is True
    assert calls == [
        (
            [sys.executable, "-c", opencv_normalizer.CV2_VERSION_PROBE],
            {"capture_output": True, "text": True, "check": False},
        )
    ]


def test_legacy_distribution_is_reset_and_revalidated(tmp_path):
    core_path = _write_core(tmp_path)
    installed = {"opencv-python": "4.14.0.94"}
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1:3] == ["-m", "pip"] and "uninstall" in command:
            installed.clear()
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[1:3] == ["-m", "pip"] and "install" in command:
            installed["opencv-contrib-python"] = "4.14.0.94"
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="4.14.0\n", stderr="")

    result = opencv_normalizer.normalize_opencv_installation(
        core_path,
        get_installed_distributions=lambda: dict(installed),
        run_command=fake_run,
        python_executable=sys.executable,
    )

    assert result is True
    assert calls == [
        [sys.executable, "-c", opencv_normalizer.CV2_VERSION_PROBE],
        [
            sys.executable,
            "-m",
            "pip",
            "uninstall",
            "-y",
            *OPENCV_DISTRIBUTIONS,
        ],
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--force-reinstall",
            "opencv-contrib-python==4.14.0.94",
        ],
        [sys.executable, "-c", opencv_normalizer.CV2_VERSION_PROBE],
    ]


def test_reconciliation_failure_returns_false_without_claiming_success(tmp_path):
    core_path = _write_core(tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if "uninstall" in command:
            return SimpleNamespace(returncode=1, stdout="", stderr="failed")
        return SimpleNamespace(returncode=0, stdout="4.14.0\n", stderr="")

    result = opencv_normalizer.normalize_opencv_installation(
        core_path,
        get_installed_distributions=lambda: {"opencv-python": "4.14.0.94"},
        run_command=fake_run,
        python_executable=sys.executable,
    )

    assert result is False
    assert any("uninstall" in command for command in calls)
    assert not any("--force-reinstall" in command for command in calls)


def test_cli_returns_nonzero_when_normalization_fails(tmp_path, monkeypatch):
    core_path = _write_core(tmp_path)
    monkeypatch.setattr(
        opencv_normalizer,
        "normalize_opencv_installation",
        lambda requirements_core_path: False,
    )

    assert (
        opencv_normalizer.main(["--requirements-core", str(core_path)])
        == 1
    )

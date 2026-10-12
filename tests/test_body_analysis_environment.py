"""Contracts for the optional, user-installed SAM3 runtime."""

import importlib.util
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

from src.services import body_analysis_environment as environment


def test_optional_body_analysis_environment_service_exists():
    assert importlib.util.find_spec("src.services.body_analysis_environment") is not None


def _model(tmp_path):
    model = tmp_path / "checkpoint"
    model.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")
    (model / "model.safetensors").write_bytes(b"synthetic")
    return model


def _fake_probe(command, **_kwargs):
    assert "-c" in command
    if "sys.implementation" in command[-1]:
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"implementation": "cpython", "version": [3, 11], "executable": command[0]}),
            stderr="",
        )
    return SimpleNamespace(returncode=0, stdout=json.dumps({"ready": True, "cuda": True}), stderr="")


def test_probe_reports_missing_checkpoint_without_loading_any_model(tmp_path):
    status = environment.probe_body_analysis_environment(
        tmp_path / "not-a-checkpoint", env_root=tmp_path / "env", python_candidates=[]
    )

    assert status["state"] == "missing_model"
    assert status["ready"] is False
    assert "model" in status["missing"]
    assert status["python_executable"] is None


def test_probe_reports_missing_python_when_no_safe_creator_is_available(tmp_path):
    status = environment.probe_body_analysis_environment(
        _model(tmp_path), env_root=tmp_path / "env", python_candidates=[]
    )

    assert status["state"] == "missing_python"
    assert status["ready"] is False
    assert "python" in status["missing"]


def test_probe_reports_missing_dependencies_in_own_venv(tmp_path):
    creator = tmp_path / "creator-python.exe"
    creator.write_bytes(b"synthetic")
    status = environment.probe_body_analysis_environment(
        _model(tmp_path), env_root=tmp_path / "env", python_candidates=[creator],
        run_command=_fake_probe,
    )

    assert status["state"] == "missing_dependencies"
    assert status["ready"] is False
    assert "dependencies" in status["missing"]
    assert status["python_executable"] is None


def test_probe_accepts_importable_sam3_and_cuda_from_own_venv(tmp_path):
    root = tmp_path / "env"
    python = environment.get_environment_python_path(root)
    python.parent.mkdir(parents=True)
    python.write_bytes(b"synthetic")
    calls = []

    def check(command, **kwargs):
        calls.append(command)
        return _fake_probe(command, **kwargs)

    status = environment.probe_body_analysis_environment(
        _model(tmp_path), env_root=root, python_candidates=[], run_command=check,
    )

    assert status["state"] == "ready"
    assert status["ready"] is True
    assert status["missing"] == []
    assert status["python_executable"] == str(python)
    assert calls[0][0] == str(python)
    assert all(str(tmp_path / "photos") not in " ".join(command) for command in calls)


def test_install_requires_explicit_user_action_and_creates_nothing_otherwise(tmp_path):
    root = tmp_path / "env"
    status = environment.install_body_analysis_environment(
        _model(tmp_path), env_root=root, python_candidates=[]
    )

    assert status["state"] == "permission_required"
    assert status["ready"] is False
    assert not root.exists()


class _FinishedProcess:
    def __init__(self, returncode=0):
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def wait(self, **_kwargs):
        return self.returncode


def test_explicit_install_uses_only_independent_venv_and_pinned_packages(tmp_path):
    model = _model(tmp_path)
    root = tmp_path / "env"
    creator = tmp_path / "creator-python.exe"
    creator.write_bytes(b"synthetic")
    commands = []

    def launch(command, **_kwargs):
        commands.append(command)
        if command[1:3] == ["-m", "venv"]:
            python = environment.get_environment_python_path(root)
            python.parent.mkdir(parents=True)
            python.write_bytes(b"synthetic")
        return _FinishedProcess()

    status = environment.install_body_analysis_environment(
        model, explicit=True, env_root=root, python_candidates=[creator],
        run_command=_fake_probe, popen_factory=launch,
    )

    python = str(environment.get_environment_python_path(root))
    assert status["state"] == "installed"
    assert status["ready"] is True
    assert status["python_executable"] == python
    assert commands[0][:3] == [str(creator), "-m", "venv"]
    assert all(command[0] in {str(creator), python} for command in commands)
    assert any("torch==" in " ".join(command) for command in commands)
    assert any("transformers==" in " ".join(command) for command in commands)
    assert any("opencv-python-headless==" in " ".join(command) for command in commands)
    assert any("scikit-image==" in " ".join(command) for command in commands)
    assert all(str(model) not in " ".join(command) for command in commands)


def test_explicit_install_reports_cancellation_without_running_packages(tmp_path):
    cancel = Event()
    cancel.set()
    commands = []
    status = environment.install_body_analysis_environment(
        _model(tmp_path), explicit=True, env_root=tmp_path / "env",
        python_candidates=[], cancel_event=cancel,
        popen_factory=lambda command, **_kwargs: commands.append(command),
    )

    assert status["state"] == "cancelled"
    assert commands == []


def test_explicit_install_reports_error_without_leaking_subprocess_output(tmp_path):
    creator = tmp_path / "creator-python.exe"
    creator.write_bytes(b"synthetic")

    def launch(_command, **_kwargs):
        return _FinishedProcess(returncode=2)

    status = environment.install_body_analysis_environment(
        _model(tmp_path), explicit=True, env_root=tmp_path / "env",
        python_candidates=[creator], run_command=_fake_probe, popen_factory=launch,
    )

    assert status["state"] == "failed"
    assert status["ready"] is False
    assert "checkpoint" not in status["reason"]

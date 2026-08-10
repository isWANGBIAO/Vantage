import runpy
import sys
from types import SimpleNamespace

import pytest

from src.scripts import install_requirements as install_module


def test_install_requirements_delegates_composed_file_to_pip(tmp_path, monkeypatch):
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text(
        "-r requirements-core.txt\npytest==9.1.1\n",
        encoding="utf-8",
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(install_module.subprocess, "run", fake_run)

    failures = install_module.install_requirements(requirements_path)

    assert failures == []
    assert calls == [
        (
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                str(requirements_path),
            ],
            {"check": False},
        )
    ]


def test_install_requirements_reports_file_when_pip_fails(tmp_path, monkeypatch):
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text("-r requirements-core.txt\n", encoding="utf-8")

    monkeypatch.setattr(
        install_module.subprocess,
        "run",
        lambda command, **kwargs: SimpleNamespace(returncode=1),
    )

    failures = install_module.install_requirements(requirements_path)

    assert failures == [str(requirements_path)]


def test_cli_reports_failed_requirements_file_and_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(
        install_module.subprocess,
        "run",
        lambda command, **kwargs: SimpleNamespace(returncode=1),
    )

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(install_module.__file__, run_name="__main__")

    assert excinfo.value.code == 1
    output = capsys.readouterr().out
    assert "Requirements file failed to install:" in output
    assert "Packages that failed to install:" not in output


def test_cli_success_does_not_exit_with_error(monkeypatch, capsys):
    monkeypatch.setattr(
        install_module.subprocess,
        "run",
        lambda command, **kwargs: SimpleNamespace(returncode=0),
    )

    runpy.run_path(install_module.__file__, run_name="__main__")

    output = capsys.readouterr().out
    assert "Requirements file failed to install:" not in output

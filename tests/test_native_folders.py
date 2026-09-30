import subprocess
from pathlib import Path

import pytest

from src.utils import native_folders


@pytest.mark.parametrize(("platform", "opener"), [("darwin", "open"), ("linux", "xdg-open")])
def test_posix_open_uses_fixed_argument_list(monkeypatch, tmp_path, platform, opener):
    folder = tmp_path / "-photos; echo unsafe"
    folder.mkdir()
    calls = []
    monkeypatch.setattr(native_folders.sys, "platform", platform)
    monkeypatch.setattr(native_folders.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    native_folders.open_directory(folder)
    assert calls[0][0] == ([opener, str(folder.resolve())],)
    assert calls[0][1]["check"] is True
    assert calls[0][1]["timeout"] == 15
    assert "shell" not in calls[0][1]


def test_windows_uses_os_file_manager(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(native_folders.sys, "platform", "win32")
    monkeypatch.setattr(native_folders.os, "startfile", calls.append, raising=False)
    native_folders.open_directory(tmp_path)
    assert calls == [str(tmp_path.resolve())]


def test_non_directory_is_rejected_before_launch(monkeypatch, tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("fixture")
    monkeypatch.setattr(native_folders.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("must not launch"))
    with pytest.raises(NotADirectoryError):
        native_folders.open_directory(target)
    with pytest.raises(FileNotFoundError):
        native_folders.open_directory(tmp_path / "missing")


def test_failed_opener_does_not_claim_success(monkeypatch, tmp_path):
    monkeypatch.setattr(native_folders.sys, "platform", "linux")

    def fail(*_args, **_kwargs):
        raise subprocess.CalledProcessError(3, ["xdg-open", str(Path(tmp_path))])

    monkeypatch.setattr(native_folders.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        native_folders.open_directory(tmp_path)

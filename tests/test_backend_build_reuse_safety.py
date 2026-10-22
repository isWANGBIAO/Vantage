"""Synthetic build outputs exercise reuse without a compiler or model files."""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core import backend_runtime_packaging as packaging
from src.scripts import build_backend_runtime as builder


@pytest.mark.parametrize("payload", [b'{"digest":', b'\xff', b'[]', b'[1]', b'null', b'1'])
def test_corrupt_or_nonobject_fingerprint_is_a_cache_miss(tmp_path, payload):
    layout = packaging.resolve_backend_runtime_layout(tmp_path)
    file = packaging.backend_runtime_fingerprint_path(layout)
    file.parent.mkdir(parents=True)
    file.write_bytes(payload)
    assert packaging.load_backend_runtime_fingerprint(layout) is None
    assert not packaging.backend_runtime_fingerprint_matches(layout, {"digest": "new"}, [])
    assert file.read_bytes() == payload


def test_fingerprint_publication_preserves_old_bytes_until_atomic_replace(tmp_path, monkeypatch):
    layout = packaging.resolve_backend_runtime_layout(tmp_path)
    packaging.write_backend_runtime_fingerprint(layout, {"digest": "old"})
    target = packaging.backend_runtime_fingerprint_path(layout)

    def interrupted_replace(*_):
        raise OSError("synthetic disk full")

    monkeypatch.setattr(os, "replace", interrupted_replace)
    with pytest.raises(OSError, match="disk full"):
        packaging.write_backend_runtime_fingerprint(layout, {"digest": "new"})
    assert json.loads(target.read_text()) == {"digest": "old"}
    assert json.loads((layout["runtime_dir"] / packaging.BACKEND_RUNTIME_FINGERPRINT_NAME).read_text()) == {"digest": "old"}
    assert not list(layout["build_root"].rglob("*.tmp"))


@pytest.mark.parametrize("keep_root", [False, True])
def test_skip_build_preserves_existing_binary_and_never_certifies_changed_sources(tmp_path, monkeypatch, keep_root):
    layout = packaging.resolve_backend_runtime_layout(tmp_path)
    layout["executable_path"].parent.mkdir(parents=True)
    layout["executable_path"].write_bytes(b"old binary")
    packaging.write_backend_runtime_fingerprint(layout, {"digest": "old source"})
    old_fingerprint = packaging.backend_runtime_fingerprint_path(layout).read_bytes()
    monkeypatch.setattr(sys, "argv", ["build_backend_runtime.py", "--skip-build", *(["--keep-build-root"] if keep_root else [])])
    monkeypatch.setattr(builder, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(builder, "validate_packaging_python_environment", lambda *_: None)
    monkeypatch.setattr(builder, "installed_distribution_closure", lambda: [])
    monkeypatch.setattr(builder, "collect_backend_runtime_resources", lambda *_: [])
    monkeypatch.setattr(builder, "build_backend_runtime_fingerprint", lambda *_, **__: {"digest": "new source"})
    monkeypatch.setattr(builder, "write_project_activity_snapshot", lambda *_, **__: SimpleNamespace(output_relative_path=Path("activity.json")))
    monkeypatch.setattr(builder, "_sync_extra_runtime_resources", lambda *_: None)
    monkeypatch.setattr(builder, "remove_conflicting_runtime_libraries", lambda *_: [])
    monkeypatch.setattr(builder, "write_backend_runtime_manifest", lambda **_: {"resource_outputs": []})
    monkeypatch.setattr(builder, "write_backend_runtime_size_report", lambda *_: {"total_mb": 1, "top_directories": [], "forbidden_packages_present": []})
    monkeypatch.setattr(builder, "validate_backend_runtime_bundle", lambda *_: [] if layout["executable_path"].exists() else ["missing binary"])
    monkeypatch.setattr(builder, "_run_pyinstaller", lambda *_: pytest.fail("skip-build must not run compiler"))
    assert builder._main_without_backend_runtime_lock() == 0
    assert layout["executable_path"].read_bytes() == b"old binary"
    assert packaging.backend_runtime_fingerprint_path(layout).read_bytes() == old_fingerprint
    assert not packaging.backend_runtime_fingerprint_matches(layout, {"digest": "new source"}, [])

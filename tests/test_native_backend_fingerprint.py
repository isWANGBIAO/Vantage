from src.core.backend_runtime_packaging import (
    PYINSTALLER_EXCLUDES, build_backend_runtime_fingerprint, collect_backend_runtime_resources,
    resolve_backend_runtime_layout, write_backend_runtime_fingerprint,
)
from tests.test_backend_runtime_packaging import _create_required_runtime_resources


def test_modular_backend_changes_invalidate_all_native_runtime_packages(tmp_path):
    _create_required_runtime_resources(tmp_path)
    domain = tmp_path / "src/backend/chat.py"
    domain.parent.mkdir(parents=True)
    domain.write_text("CONTRACT = 'before'\n", encoding="utf-8")
    resources = collect_backend_runtime_resources(tmp_path)
    before = build_backend_runtime_fingerprint(tmp_path, resources=resources, distribution_closure=[])
    domain.write_text("CONTRACT = 'after'\n", encoding="utf-8")
    after = build_backend_runtime_fingerprint(tmp_path, resources=resources, distribution_closure=[])
    assert before["digest"] != after["digest"]
    assert "src/backend/chat.py" in {entry["path"] for entry in after["inputs"]}


def test_shared_backend_does_not_collect_native_ui_or_smoke_fixtures():
    assert "src.native" in PYINSTALLER_EXCLUDES


def test_runtime_carries_its_build_platform_metadata_when_relocated(tmp_path):
    layout = resolve_backend_runtime_layout(tmp_path)
    fingerprint = {"platform": {"sys_platform": "linux", "machine": "x86_64"}}
    write_backend_runtime_fingerprint(layout, fingerprint)
    cache = (layout["build_root"] / "runtime-fingerprint.json").read_bytes()
    bundled = (layout["runtime_dir"] / "runtime-fingerprint.json").read_bytes()
    assert bundled == cache

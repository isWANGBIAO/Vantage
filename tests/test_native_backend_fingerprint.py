from src.core.backend_runtime_packaging import build_backend_runtime_fingerprint, collect_backend_runtime_resources
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

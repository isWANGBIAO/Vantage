from datetime import datetime
from pathlib import Path

import pytest

from src.core.backend_runtime_packaging import (
    APP_EXE_NAME,
    REQUIRED_ROOT_RESOURCE_NAMES,
    RUNTIME_NAME,
    build_backend_runtime_manifest,
    build_pyinstaller_arguments,
    collect_backend_runtime_resources,
    resolve_backend_runtime_layout,
)


def _create_required_runtime_resources(project_root: Path):
    (project_root / "src" / "scripts" / "models").mkdir(parents=True, exist_ok=True)
    (project_root / "src" / "scripts" / "models" / "face_parsing.farl.lapa.int8.onnx").write_bytes(b"onnx")
    (project_root / "yolo26m.pt").write_bytes(b"weights")
    for resource_name in REQUIRED_ROOT_RESOURCE_NAMES:
        (project_root / resource_name).write_text(f"# {resource_name}\n", encoding="utf-8")


def test_resolve_backend_runtime_layout_uses_fixed_output_tree(tmp_path):
    layout = resolve_backend_runtime_layout(tmp_path)

    assert layout["build_root"] == tmp_path / "build" / "backend-runtime"
    assert layout["dist_dir"] == tmp_path / "build" / "backend-runtime" / "stage"
    assert layout["work_dir"] == tmp_path / "build" / "backend-runtime" / "work"
    assert layout["spec_dir"] == tmp_path / "build" / "backend-runtime" / "spec"
    assert layout["runtime_dir"] == tmp_path / "build" / "backend-runtime" / "stage" / RUNTIME_NAME
    assert layout["manifest_path"] == layout["runtime_dir"] / "runtime-manifest.json"
    assert layout["entry_script"] == tmp_path / "src" / "scripts" / "run_server_background.py"


def test_collect_backend_runtime_resources_requires_models_and_prompts(tmp_path):
    _create_required_runtime_resources(tmp_path)

    resources = collect_backend_runtime_resources(tmp_path)

    packaged_paths = {resource.relative_destination / resource.source.name for resource in resources}
    assert Path("yolo26m.pt") in packaged_paths
    assert Path("src") / "scripts" / "models" / "face_parsing.farl.lapa.int8.onnx" in packaged_paths
    for resource_name in REQUIRED_ROOT_RESOURCE_NAMES:
        assert Path(resource_name) in packaged_paths


def test_collect_backend_runtime_resources_rejects_missing_required_files(tmp_path):
    with pytest.raises(FileNotFoundError) as excinfo:
        collect_backend_runtime_resources(tmp_path)

    assert "Prompt_Action_Plan.md" in str(excinfo.value)
    assert "yolo26m.pt" in str(excinfo.value)


def test_build_pyinstaller_arguments_include_data_files_and_fixed_layout(tmp_path):
    _create_required_runtime_resources(tmp_path)
    layout = resolve_backend_runtime_layout(tmp_path)
    resources = collect_backend_runtime_resources(tmp_path)

    args = build_pyinstaller_arguments(
        project_root=tmp_path,
        layout=layout,
        resources=resources,
    )

    assert "--onedir" in args
    assert "--console" in args
    assert "--collect-submodules" in args
    assert "src" in args
    assert "--distpath" in args
    assert str(layout["dist_dir"]) in args
    assert "--workpath" in args
    assert str(layout["work_dir"]) in args
    assert "--specpath" in args
    assert str(layout["spec_dir"]) in args
    assert "--name" in args
    assert RUNTIME_NAME in args
    assert str(layout["entry_script"]) == args[-1]
    assert f"{tmp_path / 'yolo26m.pt'};." in args
    assert (
        f"{tmp_path / 'src' / 'scripts' / 'models' / 'face_parsing.farl.lapa.int8.onnx'};"
        "src/scripts/models"
    ) in args


def test_build_backend_runtime_manifest_records_relative_outputs(tmp_path):
    _create_required_runtime_resources(tmp_path)
    layout = resolve_backend_runtime_layout(tmp_path)
    resources = collect_backend_runtime_resources(tmp_path)

    manifest = build_backend_runtime_manifest(
        layout=layout,
        resources=resources,
        built_at=datetime(2026, 4, 23, 18, 0, 0),
    )

    assert manifest["runtime_name"] == RUNTIME_NAME
    assert manifest["executable"] == f"{RUNTIME_NAME}/{APP_EXE_NAME}"
    assert manifest["generated_at"] == "2026-04-23T18:00:00"
    assert manifest["entry_script"] == "src/scripts/run_server_background.py"
    assert manifest["app_mode"] == "packaged"
    assert "yolo26m.pt" in manifest["resource_outputs"]
    assert "src/scripts/models/face_parsing.farl.lapa.int8.onnx" in manifest["resource_outputs"]

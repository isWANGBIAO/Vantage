from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.backend_runtime_packaging import (
    APP_EXE_NAME,
    BACKEND_RUNTIME_FINGERPRINT_NAME,
    CONFLICTING_RUNTIME_DLL_NAMES,
    FORBIDDEN_RUNTIME_PACKAGE_NAMES,
    PROJECT_ACTIVITY_SNAPSHOT_NAME,
    REQUIRED_ROOT_RESOURCE_NAMES,
    RUNTIME_NAME,
    backend_runtime_fingerprint_matches,
    build_backend_runtime_manifest,
    build_backend_runtime_fingerprint,
    build_pyinstaller_arguments,
    build_backend_runtime_size_report,
    build_project_activity_snapshot,
    collect_backend_runtime_resources,
    remove_conflicting_runtime_libraries,
    resolve_backend_runtime_layout,
    validate_packaging_python_environment,
    write_backend_runtime_fingerprint,
    write_project_activity_snapshot,
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

    packaged_paths = {resource.output_relative_path for resource in resources}
    assert Path("opencv-data") / "haarcascade_frontalface_default.xml" in packaged_paths
    assert Path("scienceplots") / "styles" in packaged_paths
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
    assert "--runtime-hook" in args
    runtime_hook_index = args.index("--runtime-hook") + 1
    assert args[runtime_hook_index] == str(layout["runtime_hook"])
    assert "--exclude-module" in args
    exclude_targets = {
        args[index + 1]
        for index, value in enumerate(args)
        if value == "--exclude-module"
    }
    assert "mediapipe" in exclude_targets
    assert {
        "Cython",
        "IPython",
        "jax",
        "jaxlib",
        "jedi",
        "notebook",
        "polars",
        "src.AI_Prediction",
        "src.battery_monitor",
        "src.face_analyzer_mediapipe",
        "src.scripts.debug_single_face",
        "src.scripts.install_requirements",
        "src.scripts.test_gpu_inference",
        "tensorrt",
        "tensorrt_bindings",
        "tkinter",
        "torchaudio",
    } <= exclude_targets
    assert str(layout["entry_script"]) == args[-1]
    assert f"{tmp_path / 'yolo26m.pt'};." in args
    assert (
        f"{tmp_path / 'src' / 'scripts' / 'models' / 'face_parsing.farl.lapa.int8.onnx'};"
        "src/scripts/models"
    ) in args
    assert any(
        value.endswith(";scienceplots/styles") and "scienceplots" in value and "styles" in value
        for value in args
    )


def test_remove_conflicting_runtime_libraries_deletes_known_vc_runtime_copies(tmp_path):
    runtime_dir = tmp_path / RUNTIME_NAME
    keep_file = runtime_dir / "_internal" / "torch" / "lib" / "torch_cpu.dll"
    keep_file.parent.mkdir(parents=True, exist_ok=True)
    keep_file.write_bytes(b"torch")

    removed_targets = []
    for relative_path in (
        Path("_internal") / "MSVCP140.dll",
        Path("_internal") / "VCRUNTIME140.dll",
        Path("_internal") / "VCRUNTIME140_1.dll",
        Path("_internal") / "pyzmq.libs" / "MSVCP140.dll",
    ):
        target = runtime_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"runtime")
        removed_targets.append(target)

    removed = remove_conflicting_runtime_libraries(runtime_dir)

    assert {path.name.lower() for path in removed} <= set(CONFLICTING_RUNTIME_DLL_NAMES)
    assert {path.resolve() for path in removed} == {path.resolve() for path in removed_targets}
    assert all(not path.exists() for path in removed_targets)
    assert keep_file.exists()


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


def test_validate_packaging_environment_requires_clean_runtime_venv(tmp_path):
    dirty_python = tmp_path / "global" / "python.exe"
    clean_python = tmp_path / ".venv-backend-runtime-gpu" / "Scripts" / "python.exe"

    assert validate_packaging_python_environment(tmp_path, executable=clean_python, environ={}) is None
    assert "clean packaging venv" in validate_packaging_python_environment(
        tmp_path,
        executable=dirty_python,
        environ={},
    )
    assert validate_packaging_python_environment(
        tmp_path,
        executable=dirty_python,
        environ={"VANTAGE_ALLOW_DIRTY_PACKAGING_ENV": "1"},
    ) is None


def test_build_project_activity_snapshot_parses_recent_git_log(tmp_path):
    def fake_run(command, **kwargs):
        assert command[:2] == ["git", "log"]
        assert kwargs["cwd"] == tmp_path
        return SimpleNamespace(
            returncode=0,
            stdout=b"abc1234|2026-04-24|fix packaged progress\n",
            stderr=b"",
        )

    snapshot = build_project_activity_snapshot(
        tmp_path,
        built_at=datetime(2026, 4, 24, 12, 0, 0),
        run_command=fake_run,
    )

    assert snapshot["generated_at"] == "2026-04-24T12:00:00"
    assert snapshot["commits"] == [
        {"hash": "abc1234", "date": "2026-04-24", "message": "fix packaged progress"}
    ]


def test_write_project_activity_snapshot_returns_packaged_resource(tmp_path):
    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout=b"abc1234|2026-04-24|fix packaged progress\n", stderr=b"")

    output_path = tmp_path / "build" / PROJECT_ACTIVITY_SNAPSHOT_NAME
    resource = write_project_activity_snapshot(
        tmp_path,
        output_path,
        built_at=datetime(2026, 4, 24, 12, 0, 0),
        run_command=fake_run,
    )

    assert resource.source == output_path
    assert resource.output_relative_path == Path(PROJECT_ACTIVITY_SNAPSHOT_NAME)
    assert output_path.exists()


def test_backend_runtime_size_report_flags_forbidden_packages(tmp_path):
    layout = resolve_backend_runtime_layout(tmp_path)
    internal_root = layout["resource_dir"]
    (internal_root / "torch").mkdir(parents=True)
    (internal_root / "jaxlib").mkdir()
    (internal_root / "_polars_runtime_32").mkdir()
    (internal_root / "torch" / "tiny.bin").write_bytes(b"x" * 32)
    (internal_root / "jaxlib" / "heavy.bin").write_bytes(b"x" * 64)

    report = build_backend_runtime_size_report(layout, top_n=2)

    assert set(report["forbidden_packages_present"]) == {"_polars_runtime_32", "jaxlib"}
    assert report["top_directories"][0]["name"] == "jaxlib"
    assert report["top_files"][0]["path"].endswith("jaxlib/heavy.bin")
    assert "jaxlib" in FORBIDDEN_RUNTIME_PACKAGE_NAMES


def test_backend_runtime_fingerprint_tracks_backend_inputs_not_frontend_assets(tmp_path):
    _create_required_runtime_resources(tmp_path)
    (tmp_path / "requirements-backend-runtime-gpu.txt").write_text("fastapi==0.1\n", encoding="utf-8")
    backend_file = tmp_path / "src" / "server.py"
    backend_file.parent.mkdir(parents=True, exist_ok=True)
    backend_file.write_text("print('backend v1')\n", encoding="utf-8")
    frontend_file = tmp_path / "src" / "webapp" / "src" / "App.jsx"
    frontend_file.parent.mkdir(parents=True, exist_ok=True)
    frontend_file.write_text("export default function App() { return null }\n", encoding="utf-8")

    resources = collect_backend_runtime_resources(tmp_path)

    original = build_backend_runtime_fingerprint(tmp_path, resources=resources)
    frontend_file.write_text("export default function App() { return 'changed' }\n", encoding="utf-8")
    after_frontend_change = build_backend_runtime_fingerprint(tmp_path, resources=resources)
    backend_file.write_text("print('backend v2')\n", encoding="utf-8")
    after_backend_change = build_backend_runtime_fingerprint(tmp_path, resources=resources)

    assert original["digest"] == after_frontend_change["digest"]
    assert original["digest"] != after_backend_change["digest"]
    assert any(entry["path"] == "requirements-backend-runtime-gpu.txt" for entry in original["inputs"])
    assert not any(entry["path"].startswith("src/webapp/") for entry in original["inputs"])


def test_backend_runtime_cache_match_requires_existing_runtime_and_matching_fingerprint(tmp_path):
    _create_required_runtime_resources(tmp_path)
    (tmp_path / "requirements-backend-runtime-gpu.txt").write_text("fastapi==0.1\n", encoding="utf-8")
    backend_file = tmp_path / "src" / "server.py"
    backend_file.parent.mkdir(parents=True, exist_ok=True)
    backend_file.write_text("print('backend')\n", encoding="utf-8")
    layout = resolve_backend_runtime_layout(tmp_path)
    resources = collect_backend_runtime_resources(tmp_path)
    fingerprint = build_backend_runtime_fingerprint(tmp_path, resources=resources)

    layout["runtime_dir"].mkdir(parents=True)
    layout["resource_dir"].mkdir()
    layout["executable_path"].write_bytes(b"exe")
    layout["manifest_path"].write_text("{}", encoding="utf-8")
    for resource in resources:
        packaged_path = layout["resource_dir"] / resource.output_relative_path
        if resource.source.is_dir():
            packaged_path.mkdir(parents=True, exist_ok=True)
        else:
            packaged_path.parent.mkdir(parents=True, exist_ok=True)
            packaged_path.write_bytes(b"resource")
    write_backend_runtime_fingerprint(layout, fingerprint)

    assert (layout["build_root"] / BACKEND_RUNTIME_FINGERPRINT_NAME).exists()
    assert backend_runtime_fingerprint_matches(layout, fingerprint, resources)

    changed = dict(fingerprint)
    changed["digest"] = "different"
    assert not backend_runtime_fingerprint_matches(layout, changed, resources)

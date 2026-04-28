from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import subprocess
import sys
import cv2
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


RUNTIME_NAME = "VantageBackend"
APP_EXE_NAME = f"{RUNTIME_NAME}.exe"
PROJECT_ACTIVITY_SNAPSHOT_NAME = "project_activity.json"
BACKEND_RUNTIME_FINGERPRINT_NAME = "runtime-fingerprint.json"
BACKEND_RUNTIME_FINGERPRINT_VERSION = 1
BACKEND_RUNTIME_SOURCE_INPUTS = (
    "requirements-backend-runtime-gpu.txt",
    "src/core",
    "src/manager",
    "src/scripts",
    "src/services",
    "src/utils",
    "src/output_model.py",
    "src/server.py",
)
BACKEND_RUNTIME_SOURCE_SUFFIXES = (".py",)

REQUIRED_ROOT_RESOURCE_NAMES = (
    "Prompt_Action_Plan.md",
    "Prompt_Advisor_Requirements.md",
    "Prompt_AI_Instructions.md",
    "Prompt_Goals.md",
    "Prompt_Inventory.md",
    "Prompt_Personal_Info.md",
    "Prompt_Project_Management.md",
    "Prompt_Scientific_Theory.md",
    "Prompt_System.md",
)

REQUIRED_RESOURCE_SPECS = (
    ("yolo26m.pt", "."),
    ("src/scripts/models/face_parsing.farl.lapa.int8.onnx", "src/scripts/models"),
)

OPENCV_FACE_CASCADE_NAME = "haarcascade_frontalface_default.xml"
SCIENCEPLOTS_STYLES_DIR_NAME = "styles"
CONFLICTING_RUNTIME_DLL_NAMES = (
    "msvcp140.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
)

BACKEND_RUNTIME_VENV_NAME = ".venv-backend-runtime-gpu"
DIRTY_PACKAGING_ENV_BYPASS = "VANTAGE_ALLOW_DIRTY_PACKAGING_ENV"

PYINSTALLER_EXCLUDES = (
    "Cython",
    "IPython",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "ipykernel",
    "jedi",
    "jupyter",
    "jupyter_client",
    "jupyter_core",
    "jupyter_server",
    "jax",
    "jaxlib",
    "mediapipe",
    "nbclassic",
    "nbclient",
    "nbconvert",
    "nbformat",
    "notebook",
    "polars",
    "src.AI_Prediction",
    "src.battery_monitor",
    "src.face_analyzer_mediapipe",
    "src.scripts.convert_icon",
    "src.scripts.debug_single_face",
    "src.scripts.install_requirements",
    "src.scripts.render_face_pipeline_markdown",
    "src.scripts.test_gpu_inference",
    "tensorrt",
    "tensorrt_bindings",
    "tkinter",
    "torchaudio",
)

FORBIDDEN_RUNTIME_PACKAGE_NAMES = (
    "Cython",
    "IPython",
    "_polars_runtime_32",
    "ipykernel",
    "jax",
    "jaxlib",
    "jedi",
    "jupyter",
    "jupyter_client",
    "jupyter_core",
    "jupyter_server",
    "nbclassic",
    "nbclient",
    "nbconvert",
    "nbformat",
    "notebook",
    "polars",
    "tensorrt",
    "tensorrt_bindings",
    "tkinter",
    "torchaudio",
)


@dataclass(frozen=True)
class BundledResource:
    source: Path
    relative_destination: Path

    @property
    def output_relative_path(self) -> Path:
        if str(self.relative_destination) in ("", "."):
            return Path(self.source.name)
        if self.source.is_dir():
            return self.relative_destination
        return self.relative_destination / self.source.name


def resolve_backend_runtime_layout(project_root: str | Path) -> dict[str, Path]:
    resolved_root = Path(project_root).resolve()
    build_root = resolved_root / "build" / "backend-runtime"
    dist_dir = build_root / "stage"
    runtime_dir = dist_dir / RUNTIME_NAME
    resource_dir = runtime_dir / "_internal"
    return {
        "project_root": resolved_root,
        "build_root": build_root,
        "dist_dir": dist_dir,
        "work_dir": build_root / "work",
        "spec_dir": build_root / "spec",
        "runtime_dir": runtime_dir,
        "resource_dir": resource_dir,
        "manifest_path": runtime_dir / "runtime-manifest.json",
        "entry_script": resolved_root / "src" / "scripts" / "run_server_background.py",
        "runtime_hook": resolved_root / "src" / "scripts" / "pyinstaller_runtime_hook.py",
        "executable_path": runtime_dir / APP_EXE_NAME,
    }


def validate_packaging_python_environment(
    project_root: str | Path,
    *,
    executable: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> str | None:
    resolved_environ = environ if environ is not None else os.environ
    if resolved_environ.get(DIRTY_PACKAGING_ENV_BYPASS) == "1":
        return None

    expected_venv = Path(project_root).resolve() / BACKEND_RUNTIME_VENV_NAME
    resolved_executable = Path(executable or sys.executable).resolve()
    try:
        resolved_executable.relative_to(expected_venv)
    except ValueError:
        return (
            "Backend runtime must be built with the clean packaging venv: "
            f"{expected_venv}. Set {DIRTY_PACKAGING_ENV_BYPASS}=1 only for emergency local debugging."
        )
    return None


def _normalize_destination(relative_destination: str | Path) -> Path:
    destination = Path(relative_destination)
    if str(destination) in ("", "."):
        return Path(".")
    return destination


def resolve_opencv_face_cascade_source() -> Path:
    cascade_path = Path(cv2.data.haarcascades) / OPENCV_FACE_CASCADE_NAME
    if not cascade_path.exists():
        raise FileNotFoundError(f"Missing OpenCV face cascade: {cascade_path}")
    return cascade_path.resolve()


def resolve_scienceplots_styles_source() -> Path:
    spec = importlib.util.find_spec("scienceplots")
    search_locations = getattr(spec, "submodule_search_locations", None) if spec else None
    if not search_locations:
        raise FileNotFoundError("Missing scienceplots package")

    styles_path = Path(next(iter(search_locations))) / SCIENCEPLOTS_STYLES_DIR_NAME
    if not styles_path.exists():
        raise FileNotFoundError(f"Missing scienceplots styles: {styles_path}")
    return styles_path.resolve()


def collect_backend_runtime_resources(
    project_root: str | Path,
    extra_resources: list[BundledResource] | None = None,
) -> list[BundledResource]:
    resolved_root = Path(project_root).resolve()
    resources: list[BundledResource] = []
    missing: list[str] = []

    for resource_name in REQUIRED_ROOT_RESOURCE_NAMES:
        resource_path = resolved_root / resource_name
        if not resource_path.exists():
            missing.append(resource_name)
            continue
        resources.append(BundledResource(resource_path, Path(".")))

    for relative_source, relative_destination in REQUIRED_RESOURCE_SPECS:
        resource_path = resolved_root / relative_source
        if not resource_path.exists():
            missing.append(relative_source)
            continue
        resources.append(BundledResource(resource_path, _normalize_destination(relative_destination)))

    try:
        resources.append(
            BundledResource(
                resolve_opencv_face_cascade_source(),
                Path("opencv-data"),
            )
        )
    except FileNotFoundError as exc:
        missing.append(str(exc))

    try:
        resources.append(
            BundledResource(
                resolve_scienceplots_styles_source(),
                Path("scienceplots") / SCIENCEPLOTS_STYLES_DIR_NAME,
            )
        )
    except FileNotFoundError as exc:
        missing.append(str(exc))

    if missing:
        raise FileNotFoundError(
            "Missing backend runtime resources: " + ", ".join(sorted(missing))
        )

    if extra_resources:
        resources.extend(extra_resources)

    return sorted(resources, key=lambda resource: resource.output_relative_path.as_posix())


def _decode_process_output(value) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode("gbk", errors="replace")


def build_project_activity_snapshot(
    project_root: str | Path,
    *,
    days: int = 14,
    built_at: datetime | None = None,
    run_command=None,
) -> dict[str, object]:
    resolved_root = Path(project_root).resolve()
    built_at = built_at or datetime.now()
    time_limit = (built_at - timedelta(days=days)).strftime("%Y-%m-%d")
    git_cmd = ["git", "log", f'--since="{time_limit}"', "--pretty=format:%h|%ad|%s", "--date=short"]
    run = run_command or subprocess.run
    proc = run(git_cmd, capture_output=True, cwd=resolved_root)

    commits: list[dict[str, str]] = []
    if proc.returncode == 0 and getattr(proc, "stdout", None):
        out_text = _decode_process_output(proc.stdout)
        for line in out_text.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append({"hash": parts[0], "date": parts[1], "message": parts[2]})

    return {
        "generated_at": built_at.isoformat(timespec="seconds"),
        "since": time_limit,
        "source": "git log",
        "commits": commits,
    }


def write_project_activity_snapshot(
    project_root: str | Path,
    output_path: str | Path,
    *,
    built_at: datetime | None = None,
    run_command=None,
) -> BundledResource:
    resolved_output_path = Path(output_path).resolve()
    snapshot = build_project_activity_snapshot(
        project_root,
        built_at=built_at,
        run_command=run_command,
    )
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return BundledResource(resolved_output_path, Path("."))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_directory(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total_bytes = 0
    for child in sorted(file_path for file_path in path.rglob("*") if file_path.is_file()):
        relative_child = child.relative_to(path).as_posix()
        child_hash = _sha256_file(child)
        child_size = child.stat().st_size
        total_bytes += child_size
        digest.update(
            json.dumps(
                {
                    "path": relative_child,
                    "bytes": child_size,
                    "sha256": child_hash,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    return digest.hexdigest(), total_bytes


def _fingerprint_entry(project_root: Path, source: Path, logical_path: str | Path) -> dict[str, object]:
    resolved_source = source.resolve()
    if resolved_source.is_dir():
        source_hash, source_bytes = _sha256_directory(resolved_source)
    else:
        stat = resolved_source.stat()
        source_hash = _sha256_file(resolved_source)
        source_bytes = stat.st_size
    return {
        "path": Path(logical_path).as_posix(),
        "bytes": source_bytes,
        "sha256": source_hash,
    }


def _iter_backend_source_files(project_root: Path):
    for relative_input in BACKEND_RUNTIME_SOURCE_INPUTS:
        source_path = project_root / relative_input
        if not source_path.exists():
            continue
        if source_path.is_file():
            yield source_path
            continue
        for child in source_path.rglob("*"):
            if not child.is_file():
                continue
            if child.suffix.lower() not in BACKEND_RUNTIME_SOURCE_SUFFIXES:
                continue
            if "__pycache__" in child.parts:
                continue
            yield child


def build_backend_runtime_fingerprint(
    project_root: str | Path,
    *,
    resources: list[BundledResource],
) -> dict[str, object]:
    resolved_root = Path(project_root).resolve()
    entries_by_path: dict[str, dict[str, object]] = {}

    for source_path in _iter_backend_source_files(resolved_root):
        logical_path = source_path.resolve().relative_to(resolved_root).as_posix()
        entries_by_path[logical_path] = _fingerprint_entry(resolved_root, source_path, logical_path)

    for resource in resources:
        if resource.output_relative_path.as_posix() == PROJECT_ACTIVITY_SNAPSHOT_NAME:
            continue
        logical_path = resource.output_relative_path.as_posix()
        entries_by_path[logical_path] = _fingerprint_entry(resolved_root, resource.source, logical_path)

    inputs = [entries_by_path[key] for key in sorted(entries_by_path)]
    digest_payload = {
        "version": BACKEND_RUNTIME_FINGERPRINT_VERSION,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "inputs": inputs,
    }
    digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return {
        "version": BACKEND_RUNTIME_FINGERPRINT_VERSION,
        "algorithm": "sha256",
        "python": digest_payload["python"],
        "digest": digest,
        "inputs": inputs,
    }


def backend_runtime_fingerprint_path(layout: dict[str, Path]) -> Path:
    return layout["build_root"] / BACKEND_RUNTIME_FINGERPRINT_NAME


def write_backend_runtime_fingerprint(
    layout: dict[str, Path],
    fingerprint: dict[str, object],
) -> dict[str, object]:
    fingerprint_path = backend_runtime_fingerprint_path(layout)
    fingerprint_path.parent.mkdir(parents=True, exist_ok=True)
    fingerprint_path.write_text(
        json.dumps(fingerprint, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return fingerprint


def load_backend_runtime_fingerprint(layout: dict[str, Path]) -> dict[str, object] | None:
    fingerprint_path = backend_runtime_fingerprint_path(layout)
    if not fingerprint_path.exists():
        return None
    return json.loads(fingerprint_path.read_text(encoding="utf-8"))


def build_pyinstaller_arguments(
    *,
    project_root: str | Path,
    layout: dict[str, Path],
    resources: list[BundledResource],
) -> list[str]:
    resolved_root = Path(project_root).resolve()
    args = [
        "--noconfirm",
        "--clean",
        "--onedir",
        "--console",
        "--name",
        RUNTIME_NAME,
        "--paths",
        str(resolved_root),
        "--distpath",
        str(layout["dist_dir"]),
        "--workpath",
        str(layout["work_dir"]),
        "--specpath",
        str(layout["spec_dir"]),
        "--runtime-hook",
        str(layout["runtime_hook"]),
        "--collect-submodules",
        "src",
    ]

    for module_name in PYINSTALLER_EXCLUDES:
        args.extend(["--exclude-module", module_name])

    for resource in resources:
        args.extend(
            [
                "--add-data",
                f"{resource.source};{resource.relative_destination.as_posix()}",
            ]
        )

    args.append(str(layout["entry_script"]))
    return args


def build_backend_runtime_manifest(
    *,
    layout: dict[str, Path],
    resources: list[BundledResource],
    built_at: datetime | None = None,
) -> dict[str, object]:
    built_at = built_at or datetime.now()
    project_root = layout["project_root"]

    def manifest_source_path(source: Path) -> str:
        resolved_source = source.resolve()
        try:
            return resolved_source.relative_to(project_root).as_posix()
        except ValueError:
            return resolved_source.as_posix()

    return {
        "runtime_name": RUNTIME_NAME,
        "app_mode": "packaged",
        "generated_at": built_at.isoformat(timespec="seconds"),
        "entry_script": layout["entry_script"].resolve().relative_to(project_root).as_posix(),
        "executable": f"{RUNTIME_NAME}/{APP_EXE_NAME}",
        "resource_root": f"{RUNTIME_NAME}/_internal",
        "resource_outputs": [resource.output_relative_path.as_posix() for resource in resources],
        "resources": [
            {
                "source": manifest_source_path(resource.source),
                "output": resource.output_relative_path.as_posix(),
            }
            for resource in resources
        ],
    }


def write_backend_runtime_manifest(
    *,
    layout: dict[str, Path],
    resources: list[BundledResource],
    built_at: datetime | None = None,
) -> dict[str, object]:
    manifest = build_backend_runtime_manifest(layout=layout, resources=resources, built_at=built_at)
    manifest_path = layout["manifest_path"]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return manifest


def load_backend_runtime_manifest(layout: dict[str, Path]) -> dict[str, object]:
    manifest_path = layout["manifest_path"]
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(file_path.stat().st_size for file_path in path.rglob("*") if file_path.is_file())


def _relative_posix(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def build_backend_runtime_size_report(layout: dict[str, Path], *, top_n: int = 20) -> dict[str, object]:
    resource_dir = layout["resource_dir"]
    if not resource_dir.exists():
        return {
            "resource_root": str(resource_dir),
            "total_bytes": 0,
            "total_mb": 0.0,
            "forbidden_packages_present": [],
            "top_directories": [],
            "top_files": [],
        }

    top_directories = []
    for child in resource_dir.iterdir():
        if not child.is_dir():
            continue
        size = _directory_size(child)
        top_directories.append(
            {
                "name": child.name,
                "bytes": size,
                "mb": round(size / 1024 / 1024, 2),
            }
        )
    top_directories.sort(key=lambda item: item["bytes"], reverse=True)

    top_files = []
    for file_path in resource_dir.rglob("*"):
        if not file_path.is_file():
            continue
        size = file_path.stat().st_size
        top_files.append(
            {
                "path": _relative_posix(file_path, resource_dir),
                "bytes": size,
                "mb": round(size / 1024 / 1024, 2),
            }
        )
    top_files.sort(key=lambda item: item["bytes"], reverse=True)

    total_bytes = _directory_size(resource_dir)
    forbidden_lookup = {name.lower(): name for name in FORBIDDEN_RUNTIME_PACKAGE_NAMES}
    forbidden_present = sorted(
        forbidden_lookup[child.name.lower()]
        for child in resource_dir.iterdir()
        if child.name.lower() in forbidden_lookup
    )

    return {
        "resource_root": str(resource_dir),
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / 1024 / 1024, 2),
        "forbidden_packages_present": forbidden_present,
        "top_directories": top_directories[:top_n],
        "top_files": top_files[:top_n],
    }


def write_backend_runtime_size_report(
    layout: dict[str, Path],
    *,
    top_n: int = 20,
) -> dict[str, object]:
    report = build_backend_runtime_size_report(layout, top_n=top_n)
    report_path = layout["runtime_dir"] / "runtime-size-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return report


def remove_conflicting_runtime_libraries(runtime_dir: str | Path) -> list[Path]:
    resolved_runtime_dir = Path(runtime_dir).resolve()
    if not resolved_runtime_dir.exists():
        return []

    removed_files: list[Path] = []
    conflicting_names = set(CONFLICTING_RUNTIME_DLL_NAMES)
    for dll_path in resolved_runtime_dir.rglob("*.dll"):
        if dll_path.name.lower() not in conflicting_names:
            continue
        dll_path.unlink()
        removed_files.append(dll_path.resolve())
    return sorted(removed_files)


def validate_backend_runtime_bundle(
    layout: dict[str, Path],
    resources: list[BundledResource],
) -> list[str]:
    errors: list[str] = []
    executable_path = layout["executable_path"]
    if not executable_path.exists():
        errors.append(f"Missing backend executable: {executable_path}")

    manifest_path = layout["manifest_path"]
    if not manifest_path.exists():
        errors.append(f"Missing runtime manifest: {manifest_path}")

    resource_dir = layout["resource_dir"]
    for resource in resources:
        packaged_file = resource_dir / resource.output_relative_path
        if not packaged_file.exists():
            errors.append(f"Missing bundled resource: {packaged_file}")

    if resource_dir.exists():
        forbidden_present = build_backend_runtime_size_report(layout, top_n=1)["forbidden_packages_present"]
        if forbidden_present:
            errors.append("Forbidden runtime packages bundled: " + ", ".join(forbidden_present))

    return errors


def backend_runtime_fingerprint_matches(
    layout: dict[str, Path],
    expected_fingerprint: dict[str, object],
    resources: list[BundledResource],
) -> bool:
    stored_fingerprint = load_backend_runtime_fingerprint(layout)
    if not stored_fingerprint:
        return False
    if stored_fingerprint.get("digest") != expected_fingerprint.get("digest"):
        return False
    if stored_fingerprint.get("version") != expected_fingerprint.get("version"):
        return False
    if stored_fingerprint.get("python") != expected_fingerprint.get("python"):
        return False
    return not validate_backend_runtime_bundle(layout, resources)

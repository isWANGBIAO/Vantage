from __future__ import annotations

import json
import cv2
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


RUNTIME_NAME = "VantageBackend"
APP_EXE_NAME = f"{RUNTIME_NAME}.exe"

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
CONFLICTING_RUNTIME_DLL_NAMES = (
    "msvcp140.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
)

PYINSTALLER_EXCLUDES = ("PyQt5", "PyQt6", "PySide2", "PySide6", "mediapipe")


@dataclass(frozen=True)
class BundledResource:
    source: Path
    relative_destination: Path

    @property
    def output_relative_path(self) -> Path:
        if str(self.relative_destination) in ("", "."):
            return Path(self.source.name)
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


def collect_backend_runtime_resources(project_root: str | Path) -> list[BundledResource]:
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

    if missing:
        raise FileNotFoundError(
            "Missing backend runtime resources: " + ", ".join(sorted(missing))
        )

    return sorted(resources, key=lambda resource: resource.output_relative_path.as_posix())


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

    return errors

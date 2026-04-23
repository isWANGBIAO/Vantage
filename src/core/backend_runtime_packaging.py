from __future__ import annotations

import json
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

PYINSTALLER_EXCLUDES = ("PyQt5", "PyQt6", "PySide2", "PySide6")


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
        "executable_path": runtime_dir / APP_EXE_NAME,
    }


def _normalize_destination(relative_destination: str | Path) -> Path:
    destination = Path(relative_destination)
    if str(destination) in ("", "."):
        return Path(".")
    return destination


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
                "source": resource.source.resolve().relative_to(project_root).as_posix(),
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

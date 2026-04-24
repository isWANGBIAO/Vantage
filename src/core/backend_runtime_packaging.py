from __future__ import annotations

import importlib.util
import json
import subprocess
import cv2
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


RUNTIME_NAME = "VantageBackend"
APP_EXE_NAME = f"{RUNTIME_NAME}.exe"
PROJECT_ACTIVITY_SNAPSHOT_NAME = "project_activity.json"

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

PYINSTALLER_EXCLUDES = ("PyQt5", "PyQt6", "PySide2", "PySide6", "mediapipe")


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

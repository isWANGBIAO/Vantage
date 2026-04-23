from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def _ensure_project_root_on_sys_path(
    script_path: str | Path | None = None,
    path_list: list[str] | None = None,
) -> Path:
    current_script = Path(script_path or __file__).resolve()
    project_root = current_script.parents[2]
    resolved_path_list = path_list if path_list is not None else sys.path
    project_root_str = str(project_root)
    if project_root_str not in resolved_path_list:
        resolved_path_list.insert(0, project_root_str)
    return project_root


PROJECT_ROOT = _ensure_project_root_on_sys_path()

from src.core.backend_runtime_packaging import (
    build_pyinstaller_arguments,
    collect_backend_runtime_resources,
    remove_conflicting_runtime_libraries,
    resolve_backend_runtime_layout,
    validate_backend_runtime_bundle,
    write_backend_runtime_manifest,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the packaged Vantage backend runtime with PyInstaller.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Reuse the current runtime directory and only refresh the manifest and validation.",
    )
    parser.add_argument(
        "--keep-build-root",
        action="store_true",
        help="Do not remove the existing build/backend-runtime directory before building.",
    )
    return parser


def _clean_existing_build(layout: dict[str, Path]):
    build_root = layout["build_root"]
    if build_root.exists():
        shutil.rmtree(build_root)


def _run_pyinstaller(pyinstaller_args: list[str]):
    try:
        from PyInstaller.__main__ import run as run_pyinstaller
    except ImportError as exc:
        raise RuntimeError("PyInstaller is required to build the backend runtime.") from exc

    run_pyinstaller(pyinstaller_args)


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    layout = resolve_backend_runtime_layout(PROJECT_ROOT)
    resources = collect_backend_runtime_resources(PROJECT_ROOT)

    if not args.keep_build_root:
        _clean_existing_build(layout)

    layout["build_root"].mkdir(parents=True, exist_ok=True)

    if not args.skip_build:
        pyinstaller_args = build_pyinstaller_arguments(
            project_root=PROJECT_ROOT,
            layout=layout,
            resources=resources,
        )
        _run_pyinstaller(pyinstaller_args)

    removed_runtime_dlls = remove_conflicting_runtime_libraries(layout["runtime_dir"])
    manifest = write_backend_runtime_manifest(layout=layout, resources=resources)
    errors = validate_backend_runtime_bundle(layout, resources)
    if errors:
        for error in errors:
            print(error)
        return 1

    print(f"Built backend runtime: {layout['executable_path']}")
    print(f"Runtime manifest: {layout['manifest_path']}")
    print(f"Bundled resources: {len(manifest['resource_outputs'])}")
    print(f"Removed conflicting runtime DLLs: {len(removed_runtime_dlls)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

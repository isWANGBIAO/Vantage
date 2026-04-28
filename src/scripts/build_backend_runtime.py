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
    PROJECT_ACTIVITY_SNAPSHOT_NAME,
    backend_runtime_fingerprint_matches,
    build_backend_runtime_fingerprint,
    build_pyinstaller_arguments,
    collect_backend_runtime_resources,
    remove_conflicting_packaging_environment_libraries,
    remove_conflicting_runtime_libraries,
    resolve_backend_runtime_layout,
    validate_packaging_python_environment,
    validate_backend_runtime_bundle,
    write_backend_runtime_fingerprint,
    write_backend_runtime_size_report,
    write_backend_runtime_manifest,
    write_project_activity_snapshot,
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
    parser.add_argument(
        "--reuse-if-unchanged",
        action="store_true",
        help="Reuse the existing PyInstaller runtime when backend inputs have not changed.",
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


def _sync_extra_runtime_resources(layout: dict[str, Path], resources):
    resource_dir = layout["resource_dir"]
    for resource in resources:
        target = resource_dir / resource.output_relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resource.source, target)


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    layout = resolve_backend_runtime_layout(PROJECT_ROOT)
    environment_error = validate_packaging_python_environment(PROJECT_ROOT)
    if environment_error:
        print(environment_error)
        return 1

    static_resources = collect_backend_runtime_resources(PROJECT_ROOT)
    runtime_fingerprint = build_backend_runtime_fingerprint(
        PROJECT_ROOT,
        resources=static_resources,
    )

    if args.reuse_if_unchanged and backend_runtime_fingerprint_matches(
        layout,
        runtime_fingerprint,
        static_resources,
    ):
        project_activity_resource = write_project_activity_snapshot(
            PROJECT_ROOT,
            layout["build_root"] / PROJECT_ACTIVITY_SNAPSHOT_NAME,
        )
        _sync_extra_runtime_resources(layout, [project_activity_resource])
        resources = sorted(
            [*static_resources, project_activity_resource],
            key=lambda resource: resource.output_relative_path.as_posix(),
        )
        manifest = write_backend_runtime_manifest(layout=layout, resources=resources)
        size_report = write_backend_runtime_size_report(layout)
        write_backend_runtime_fingerprint(layout, runtime_fingerprint)
        print("Backend runtime unchanged; reused existing PyInstaller output.")
        print(f"Built backend runtime: {layout['executable_path']}")
        print(f"Runtime manifest: {layout['manifest_path']}")
        print(f"Bundled resources: {len(manifest['resource_outputs'])}")
        print("Removed conflicting runtime DLLs: 0")
        print(f"Runtime size: {size_report['total_mb']} MB")
        if size_report["forbidden_packages_present"]:
            print("Forbidden runtime packages present: " + ", ".join(size_report["forbidden_packages_present"]))
        else:
            print("Forbidden runtime packages present: none")
        return 0

    if not args.keep_build_root:
        _clean_existing_build(layout)

    removed_packaging_dlls = remove_conflicting_packaging_environment_libraries(PROJECT_ROOT)
    layout["build_root"].mkdir(parents=True, exist_ok=True)
    project_activity_resource = write_project_activity_snapshot(
        PROJECT_ROOT,
        layout["build_root"] / PROJECT_ACTIVITY_SNAPSHOT_NAME,
    )
    resources = sorted(
        [*static_resources, project_activity_resource],
        key=lambda resource: resource.output_relative_path.as_posix(),
    )

    if not args.skip_build:
        pyinstaller_args = build_pyinstaller_arguments(
            project_root=PROJECT_ROOT,
            layout=layout,
            resources=resources,
        )
        _run_pyinstaller(pyinstaller_args)
    else:
        _sync_extra_runtime_resources(layout, [project_activity_resource])

    removed_runtime_dlls = remove_conflicting_runtime_libraries(layout["runtime_dir"])
    manifest = write_backend_runtime_manifest(layout=layout, resources=resources)
    size_report = write_backend_runtime_size_report(layout)
    write_backend_runtime_fingerprint(layout, runtime_fingerprint)
    errors = validate_backend_runtime_bundle(layout, resources)
    if errors:
        for error in errors:
            print(error)
        return 1

    print(f"Built backend runtime: {layout['executable_path']}")
    print(f"Runtime manifest: {layout['manifest_path']}")
    print(f"Bundled resources: {len(manifest['resource_outputs'])}")
    print(f"Removed conflicting packaging DLLs: {len(removed_packaging_dlls)}")
    print(f"Removed conflicting runtime DLLs: {len(removed_runtime_dlls)}")
    print(f"Runtime size: {size_report['total_mb']} MB")
    if size_report["top_directories"]:
        print("Largest runtime directories:")
        for entry in size_report["top_directories"][:10]:
            print(f"  {entry['name']}: {entry['mb']} MB")
    if size_report["forbidden_packages_present"]:
        print("Forbidden runtime packages present: " + ", ".join(size_report["forbidden_packages_present"]))
    else:
        print("Forbidden runtime packages present: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

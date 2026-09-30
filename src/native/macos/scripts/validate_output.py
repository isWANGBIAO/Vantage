#!/usr/bin/env python3
"""Validate native macOS output ownership before any bundle is replaced."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import unicodedata

MARKER = {"format": "vantage-native-macos-bundle", "version": 1}
MARKER_PATH = Path("Contents/Resources/vantage-native-package.json")


def is_same_or_descendant(child: Path, parent: Path) -> bool:
    """Conservative component comparison for default macOS filesystem aliases.

    APFS/HFS+ commonly ignore case and canonical Unicode spelling. Do not use a
    string prefix: /Runtime-other must never be mistaken for /Runtime's child.
    """
    def components(path: Path) -> tuple[str, ...]:
        return tuple(unicodedata.normalize("NFD", part).casefold() for part in path.parts)
    child_parts, parent_parts = components(child), components(parent)
    return child_parts[:len(parent_parts)] == parent_parts


def validate_existing_bundle(target: Path) -> None:
    if not target.exists() and not target.is_symlink():
        return
    if target.is_symlink() or not target.is_dir():
        raise ValueError("Refusing to replace an output that is not a regular generated app directory.")
    marker = target / MARKER_PATH
    info = target / "Contents/Info.plist"
    if any(path.is_symlink() for path in (target / "Contents", target / "Contents/Resources", marker, info)):
        raise ValueError("Refusing an existing bundle with redirected ownership metadata.")
    try:
        if marker.stat().st_size > 4096 or info.stat().st_size > 65536:
            raise ValueError("Existing output metadata is oversized.")
        if json.loads(marker.read_text(encoding="utf-8")) != MARKER:
            raise ValueError("Existing output has no recognized Vantage package ownership marker.")
        with info.open("rb") as source:
            bundle = plistlib.load(source)
        if bundle.get("CFBundleIdentifier") != "app.vantage.native":
            raise ValueError("Existing output belongs to another app.")
    except (OSError, json.JSONDecodeError, plistlib.InvalidFileException) as error:
        raise ValueError("Existing Vantage.app is not a recognized generated output; choose a new output directory.") from error


def reject_symlink_components(path: Path) -> None:
    absolute = path.absolute()
    if any(component.is_symlink() for component in (absolute, *absolute.parents)):
        raise ValueError("Package input and output paths must not traverse symbolic links.")


def configured_data_paths() -> list[Path]:
    paths = [Path.home() / "Library/Application Support/Vantage"]
    for suffix in ("DATA", "CONFIG", "HISTORY", "LOG", "PLOT", "CACHE", "RUNTIME", "MIGRATION"):
        value = os.environ.get(f"VANTAGE_{suffix}_DIR")
        if value:
            paths.append(Path(value).expanduser())
    return paths


def validate_output(runtime: Path, output: Path, *, repository: Path | None = None, data_paths: list[Path] | None = None) -> Path:
    if any(ord(character) < 32 for character in str(runtime) + str(output)):
        raise ValueError("Build paths cannot contain control characters.")
    reject_symlink_components(runtime)
    reject_symlink_components(output)
    runtime = runtime.resolve(strict=True)
    output = output.resolve(strict=False)
    target = output / "Vantage.app"
    # Staging is under output. Never put it under its input, or replace a bundle
    # that contains the runtime being read (including symlink-resolved paths).
    if is_same_or_descendant(output, runtime) or is_same_or_descendant(runtime, target):
        raise ValueError("Backend runtime and application output paths overlap.")
    if repository is not None:
        repository = repository.resolve(strict=True)
        if is_same_or_descendant(repository, output):
            raise ValueError("Output cannot be the repository or one of its ancestors.")
        if is_same_or_descendant(output, repository) and not any(is_same_or_descendant(output, repository / name) for name in ("build", "dist")):
            raise ValueError("Inside the repository, use a build/ or dist/ output directory.")
    for data in configured_data_paths() if data_paths is None else data_paths:
        data = data.resolve(strict=False)
        if is_same_or_descendant(output, data) or is_same_or_descendant(data, output):
            raise ValueError("Output cannot overlap a Vantage personal data directory.")
    if output.exists() and not output.is_dir():
        raise ValueError("Output must be a directory.")
    validate_existing_bundle(target)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(validate_output(args.runtime, args.output, repository=args.repository))
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"Unsafe package output: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

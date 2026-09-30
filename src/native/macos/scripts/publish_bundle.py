#!/usr/bin/env python3
"""Publish a verified generated app without deleting an existing bundle."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
import tempfile

from validate_output import is_same_or_descendant, reject_symlink_components, validate_existing_bundle


def publish_bundle(staged: Path, target: Path, *, rename=os.rename) -> Path | None:
    reject_symlink_components(staged)
    reject_symlink_components(target)
    if not staged.is_dir() or target.name != "Vantage.app":
        raise ValueError("A generated staged app and a Vantage.app target are required.")
    staged_path, target_path = staged.resolve(), target.resolve(strict=False)
    if is_same_or_descendant(staged_path, target_path) or is_same_or_descendant(target_path, staged_path):
        raise ValueError("Staged app and target cannot overlap, including macOS filename aliases.")
    validate_existing_bundle(staged)
    validate_existing_bundle(target)
    backup = None
    if target.exists():
        backup = Path(tempfile.mkdtemp(prefix=".vantage-previous.", dir=target.parent)) / "Vantage.app"
        rename(target, backup)
    try:
        # Unlike mv, rename never silently nests the new app in a concurrently
        # created nonempty target. A failure restores or preserves the old app.
        rename(staged, target)
    except BaseException:
        if backup is not None and backup.exists() and not target.exists():
            try:
                rename(backup, target)
            except OSError:
                pass  # The backup remains intact for manual recovery.
        if backup is not None and backup.exists():
            print(f"Previous bundle preserved at {backup}", file=sys.stderr)
        raise
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    try:
        backup = publish_bundle(args.app, args.target)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Package publication failed without deleting previous output: {error}\n")
    if backup:
        print(backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

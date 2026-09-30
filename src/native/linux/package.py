#!/usr/bin/env python3
"""Create a relocatable Linux native archive with a mandatory backend runtime.

GTK4/PyGObject come from the Linux distribution. No package installation or
network download occurs in this script. The backend tree must be prebuilt.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import uuid



MARKER_NAME = ".vantage-linux-package.json"
MARKER_FORMAT = "vantage-linux-native-package"


def package_marker(architecture):
    return {"format": MARKER_FORMAT, "version": 1, "architecture": architecture}


def resolve_output_directory(output, runtime_root, source, repo, *, data_roots=None):
    """Reject locations that would mix generated output with protected inputs."""
    requested = Path(output).expanduser().absolute()
    if any(part.is_symlink() for part in (requested, *requested.parents)):
        raise ValueError("The package output directory must not use symbolic links")
    resolved = requested.resolve()
    repo = Path(repo).resolve()
    if resolved == repo or repo.is_relative_to(resolved):
        raise ValueError("The package output must not be the repository or one of its ancestors")
    protected = [Path(runtime_root).resolve(), Path(source).resolve()]
    if data_roots is None:
        data_roots = [Path.home() / ".local/share/Vantage"]
        data_roots.extend(Path(value).expanduser() for key in (
            "VANTAGE_DATA_DIR", "VANTAGE_HISTORY_DIR", "VANTAGE_CONFIG_DIR",
            "VANTAGE_LOG_DIR", "VANTAGE_PLOT_DIR", "VANTAGE_CACHE_DIR",
            "VANTAGE_RUNTIME_DIR", "VANTAGE_MIGRATION_DIR",
        ) if (value := os.environ.get(key)))
    protected.extend(Path(path).resolve() for path in data_roots)
    if any(resolved == root or resolved.is_relative_to(root) for root in protected):
        raise ValueError("The package output must be outside backend, client-source and user-data input trees")
    return resolved


def validate_stage_location(stage, runtime_root):
    if Path(stage).resolve().is_relative_to(Path(runtime_root).resolve()):
        raise ValueError("The package staging directory must not be inside the backend source tree")


def target_signature(directory_fd, name, architecture):
    """Identify only archives produced by this packager, without following links."""
    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("Refusing to overwrite a symbolic link, directory or special file at the package target")
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    with os.fdopen(descriptor, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise ValueError("The package target changed while it was being inspected")
        owned = False
        try:
            with tarfile.open(fileobj=handle, mode="r|gz") as archive:
                # Our archive writes the root directory then the marker first.
                # Do not scan unrelated archive payloads looking for permission.
                for member in archive:
                    if member.name.rstrip("/") == "Vantage" and member.isdir():
                        continue
                    if member.name != f"Vantage/{MARKER_NAME}" or not member.isfile() or member.size > 4096:
                        break
                    marker = archive.extractfile(member)
                    owned = marker is not None and json.loads(marker.read(4097)) == package_marker(architecture)
                    break
        except (tarfile.TarError, OSError, ValueError, UnicodeError):
            owned = False
        if not owned:
            raise ValueError("The existing package target is not a marked Vantage build; choose another output directory")
    return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns)


def atomic_archive(stage, output, architecture):
    """Publish a complete archive without ever opening the final path for writing."""
    name = f"Vantage-linux-{architecture}.tar.gz"
    directory_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary_name = f".vantage-archive-{uuid.uuid4().hex}.tmp"
    temporary_created = False
    try:
        before = target_signature(directory_fd, name, architecture)
        descriptor = os.open(
            temporary_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=directory_fd,
        )
        temporary_created = True
        with os.fdopen(descriptor, "wb") as handle:
            with tarfile.open(fileobj=handle, mode="w:gz") as archive:
                archive.add(stage, arcname="Vantage")
            handle.flush()
            os.fsync(handle.fileno())
        after = target_signature(directory_fd, name, architecture)
        if after != before:
            raise ValueError("The package target changed during the build; it was not replaced")
        if before is None:
            # Atomic no-clobber publication protects a newly appearing unrelated
            # target after the check. Both names are anchored to the open dirfd.
            os.link(temporary_name, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
            os.unlink(temporary_name, dir_fd=directory_fd)
        else:
            # Replacing an approved old artifact replaces a symlink itself if a
            # concurrent writer races us; it never follows it to another file.
            os.replace(temporary_name, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        temporary_created = False
        os.fsync(directory_fd)
    finally:
        try:
            if temporary_created:
                try:
                    os.unlink(temporary_name, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
        finally:
            os.close(directory_fd)
    return Path(output) / name


def package(runtime, output, cjk_font=None, font_license=None):
    runtime = Path(runtime).resolve()
    executable = runtime / "VantageBackend" if runtime.is_dir() else runtime
    runtime_root = executable.parent
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("--backend-runtime must contain an executable VantageBackend; backend-free archives are not supported")
    repo = Path(__file__).resolve().parents[3]
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from scripts.validate_native_runtime import validate_runtime
    validate_runtime(runtime_root, "linux", platform.machine())
    cjk_font = Path(cjk_font or "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    font_license = Path(font_license or "/usr/share/doc/fonts-noto-cjk/copyright")
    if not cjk_font.is_file() or not font_license.is_file():
        raise ValueError("Install the official fonts-noto-cjk package, or supply --cjk-font and --font-license; native packages must include a licensed CJK font")
    source = Path(__file__).resolve().parent
    output = resolve_output_directory(output, runtime_root, source, repo)
    output.mkdir(parents=True, exist_ok=True)
    arch = platform.machine()
    directory_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        target_signature(directory_fd, f"Vantage-linux-{arch}.tar.gz", arch)
    finally:
        os.close(directory_fd)
    # Stage beside the eventual archive, outside the input tree. The explicit
    # check also guards custom temporary-directory configurations.
    with tempfile.TemporaryDirectory(prefix=".vantage-linux-stage-", dir=output) as temporary:
        stage = Path(temporary) / "Vantage"
        validate_stage_location(stage, runtime_root)
        stage.mkdir()
        (stage / MARKER_NAME).write_text(json.dumps(package_marker(arch)), encoding="utf-8")
        shutil.copy2(source / "main.py", stage / "main.py")
        shutil.copytree(source / "vantage_linux", stage / "vantage_linux", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(runtime_root, stage / "backend", symlinks=True)
        shutil.copy2(source / "README.md", stage / "README.md")
        shutil.copy2(source.parents[2] / "LICENSE", stage / "LICENSE")
        (stage / "fonts").mkdir()
        shutil.copy2(cjk_font, stage / "fonts" / cjk_font.name)
        shutil.copy2(font_license, stage / "fonts" / "LICENSE.txt")
        launcher = stage / "vantage"
        launcher.write_text('#!/bin/sh\nset -eu\nROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec /usr/bin/python3 "$ROOT/main.py" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
        installer = stage / "install-desktop-entry"
        installer.write_text('''#!/usr/bin/python3
from pathlib import Path
import os
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from vantage_linux.platform import desktop_quote
root = Path(__file__).resolve().parent
folder = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"
folder.mkdir(parents=True, exist_ok=True)
(folder / "org.vantage.Native.desktop").write_text("[Desktop Entry]\\nType=Application\\nName=Vantage\\nExec=" + desktop_quote(root / "vantage") + "\\nIcon=applications-science\\nTerminal=false\\nCategories=Utility;Office;\\n", encoding="utf-8")
print("Installed user desktop entry")
''', encoding="utf-8")
        installer.chmod(0o755)
        target = atomic_archive(stage, output, arch)
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-runtime", required=True, type=Path)
    parser.add_argument("--output-dir", default="dist/native/linux", type=Path)
    parser.add_argument("--cjk-font", type=Path)
    parser.add_argument("--font-license", type=Path)
    args = parser.parse_args()
    try:
        print(package(args.backend_runtime, args.output_dir, args.cjk_font, args.font_license))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()

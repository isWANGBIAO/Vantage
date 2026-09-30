#!/usr/bin/env python3
"""Create a relocatable Linux native archive with a mandatory backend runtime.

GTK4/PyGObject come from the Linux distribution. No package installation or
network download occurs in this script. The backend tree must be prebuilt.
"""
import argparse
import os
from pathlib import Path
import platform
import shutil
import sys
import tarfile
import tempfile


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
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    arch = platform.machine()
    target = output / f"Vantage-linux-{arch}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="vantage-linux-package-") as temporary:
        stage = Path(temporary) / "Vantage"
        stage.mkdir()
        source = Path(__file__).resolve().parent
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
        with tarfile.open(target, "w:gz") as archive:
            archive.add(stage, arcname="Vantage")
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

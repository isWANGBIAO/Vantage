"""Open an already authorized local directory using the desktop's file manager."""

import os
import subprocess
import sys
from pathlib import Path


def open_directory(path: str | Path) -> None:
    # Resolve first so POSIX paths beginning with '-' cannot become options.
    target = Path(path).resolve(strict=True)
    if not target.is_dir():
        raise NotADirectoryError("The selected location is not a directory.")
    if sys.platform == "win32":
        os.startfile(str(target))
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    # A list, never a shell command. Waiting for the opener reports unavailable
    # desktop sessions/missing tools rather than claiming a folder was opened.
    subprocess.run(
        [opener, str(target)], check=True, timeout=15,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

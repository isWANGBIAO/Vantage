#!/usr/bin/env python3
"""Source and packaged GTK4 entry point."""
import argparse
import os
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="Vantage native GTK4 client")
    parser.add_argument("--backend-url")
    parser.add_argument("--backend-runtime", type=Path)
    parser.add_argument("--backend-python", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--connect-only", action="store_true")
    parser.add_argument("--check", action="store_true", help="Check GTK4 dependencies without starting backend")
    args = parser.parse_args(argv)
    from vantage_linux.fonts import register_bundled_fonts
    register_bundled_fonts(Path(__file__).resolve().parent)
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk
        import cairo  # Gtk.DrawingArea callbacks need PyCairo
    except (ImportError, ValueError):
        print("GTK4 dependencies missing. Install your distro's python3-gi, python3-cairo, python3-gi-cairo and gir1.2-gtk-4.0, then use /usr/bin/python3.", file=sys.stderr)
        return 2
    if args.check:
        print(f"GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()} / PyGObject ready")
        return 0
    from vantage_linux.client import Client, ClientError
    from vantage_linux.lifecycle import BackendHost
    from vantage_linux.application import Application
    root = Path(__file__).resolve().parent
    runtime = args.backend_runtime or root / "backend" / "VantageBackend"
    command = None
    if not args.connect_only:
        if runtime.is_file():
            command = [str(runtime.resolve())]
        elif args.backend_runtime:
            print("Backend runtime does not exist", file=sys.stderr)
            return 2
        elif args.backend_python:
            repo = root.parents[2]
            command = [str(args.backend_python.resolve()), str(repo / "src/scripts/run_server_background.py")]
    try:
        client = Client(args.backend_url)
    except ClientError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    host = BackendHost(client, command, args.data_dir)
    launch_command = [sys.executable, str(Path(__file__).resolve()), *(argv if argv is not None else sys.argv[1:])]
    application = Application(host, launch_command)
    try:
        return application.run([sys.argv[0]])
    finally:
        host.close()


if __name__ == "__main__":
    raise SystemExit(main())

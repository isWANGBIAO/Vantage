"""Run a packaged native desktop window against isolated synthetic API data."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.native.testing.fixture_backend import start_fixture

REQUIRED_PAGES = frozenset({
    "dashboard", "action-plan", "chat", "usage", "projects", "finance",
    "plots", "face", "logs", "settings",
})


def validate_report(report: object) -> None:
    if not isinstance(report, dict) or report.get("success") is not True:
        raise ValueError("Native smoke did not report success.")
    if report.get("errors"):
        raise ValueError("Native smoke reported UI errors.")
    pages = report.get("pages")
    if not isinstance(pages, list):
        raise ValueError("Native smoke must report tested pages.")
    loaded = {
        page.get("id") for page in pages
        if isinstance(page, dict) and page.get("loaded") is True
    }
    missing = REQUIRED_PAGES - loaded
    if missing:
        raise ValueError("Native smoke missed loaded pages: " + ", ".join(sorted(missing)))


def isolated_environment(base_url: str, root: Path) -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(("VANTAGE_", "OPENAI_", "CLIPROXYAPI_", "ANTHROPIC_", "AZURE_OPENAI_"))
        and not any(marker in key.upper() for marker in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))
    }
    env["VANTAGE_BACKEND_URL"] = base_url
    env["VANTAGE_NATIVE_SMOKE"] = "1"
    for key, child in {
        "DATA": "data", "CONFIG": "config", "HISTORY": "history", "LOG": "logs",
        "PLOT": "plots", "CACHE": "cache", "RUNTIME": "runtime", "MIGRATION": "migration",
    }.items():
        env[f"VANTAGE_{key}_DIR"] = str(root / child)
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args(argv)
    client = args.client.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "report.json"
    # A previous passing report must never make a failed run look successful.
    if report_path.exists():
        report_path.unlink()
    server = start_fixture()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with tempfile.TemporaryDirectory(prefix="vantage-native-smoke-") as temporary:
            env = isolated_environment(base_url, Path(temporary))
            with (output / "stdout.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    [str(client), "--smoke-test", str(report_path)],
                    cwd=client.parent, env=env, stdout=log, stderr=subprocess.STDOUT,
                )
                try:
                    code = process.wait(timeout=args.timeout_seconds)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
            if code:
                raise RuntimeError(f"Native application exited with status {code}; see smoke evidence.")
            validate_report(json.loads(report_path.read_text(encoding="utf-8")))
            (output / "requests.json").write_text(
                json.dumps(server.state["requests"], indent=2), encoding="utf-8",
            )
    finally:
        server.shutdown()
        server.server_close()
    print("Native window smoke passed against synthetic data; no live model/hardware checks were performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

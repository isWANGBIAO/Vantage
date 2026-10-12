"""Lifespan-owned, local-only SAM3 report supervision.

The frozen backend never loads ML libraries or source image pixels. Its only
durable state is an atomically selected, fully validated generated report.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable

from src.core.config import Config
from src.core.user_config import get_body_analysis_report_root, load_settings, validate_body_analysis_paths
from src.scripts.body_analysis_sam3 import IMAGE_SUFFIXES, ASSET_SUFFIXES, validate_report_manifest
from src.services.body_analysis_environment import (
    install_body_analysis_environment, probe_body_analysis_environment,
)


@dataclass(frozen=True)
class SourceSnapshot:
    fingerprint: str
    counts: dict[str, int]


def _files(root: Path, suffixes: frozenset[str] | None = None) -> list[Path]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("source_unavailable")
    resolved_root = root.resolve()
    found = []
    for path in root.rglob("*"):
        if path.is_symlink() or not path.resolve().is_relative_to(resolved_root):
            raise ValueError("source_link_forbidden")
        if path.is_file() and (suffixes is None or path.suffix.lower() in suffixes):
            found.append(path)
        if len(found) > 200_000:
            raise ValueError("too_many_source_files")
    return sorted(found)


def source_snapshot(paths: dict[str, Path], runner_path: Path) -> SourceSnapshot:
    """Hash only file metadata, relative names, and runner bytes (never pixels)."""
    runner = Path(runner_path)
    if not runner.is_file() or runner.is_symlink():
        raise ValueError("runner_unavailable")
    digest = hashlib.sha256()
    digest.update(b"body-analysis-snapshot-v1\0")
    digest.update(hashlib.sha256(runner.read_bytes()).digest())
    counts = {}
    for kind in ("leg", "scalp", "model"):
        root = Path(paths[kind])
        # Two different configured roots can contain byte-identical files and
        # matching metadata. The digest must still distinguish their identity.
        # No root path is stored outside this one-way fingerprint.
        digest.update(os.path.normcase(str(root.resolve())).encode("utf-8") + b"\0")
        files = _files(root, IMAGE_SUFFIXES if kind != "model" else None)
        if kind != "model":
            counts[kind] = len(files)
        digest.update(kind.encode() + b"\0")
        for path in files:
            stat = path.stat()
            digest.update(json.dumps(
                [path.relative_to(root).as_posix(), stat.st_size, stat.st_mtime_ns],
                ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8") + b"\0")
    return SourceSnapshot(digest.hexdigest(), counts)


def _write_json_atomically(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _has_absolute_path(value: object) -> bool:
    """Do not publish even accidental local paths in extensible report fields."""
    if isinstance(value, str):
        return PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()
    if isinstance(value, dict):
        return any(_has_absolute_path(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_absolute_path(item) for item in value)
    return False


def _public_environment(value: dict) -> dict:
    reason = value.get("reason")
    missing = value.get("missing")
    return {
        "ready": value.get("ready") is True,
        "reason": reason if isinstance(reason, str) and re.fullmatch(r"[a-z_]{1,64}", reason) else "unavailable",
        "missing": [item for item in missing if item in {"model", "python", "dependencies", "cuda"}]
        if isinstance(missing, list) else [],
    }


def _discard_generated_staging(staging_root: Path, output: Path) -> None:
    """Remove only this service's uniquely named temporary output, never sources."""
    if output.parent.resolve() != staging_root.resolve() or not re.fullmatch(r"[0-9a-f]{32}", output.name):
        return
    if output.is_dir() and not output.is_symlink():
        shutil.rmtree(output)


def _runner_path() -> Path:
    return Path(Config.get_project_root()) / "src" / "scripts" / "body_analysis_sam3.py"


class BodyAnalysisJobService:
    def __init__(self, *, root: Path | None = None, settings_loader: Callable = load_settings,
                 environment_probe: Callable = probe_body_analysis_environment,
                 environment_installer: Callable = install_body_analysis_environment,
                 runner_path: Path | None = None):
        self._root_error = False
        try:
            self.root = Path(root) if root is not None else get_body_analysis_report_root()
        except ValueError:
            # A broken user-data override must not prevent the whole backend
            # (including settings so the user can recover) from starting.
            self.root = None
            self._root_error = True
        self.settings_loader = settings_loader
        self.environment_probe = environment_probe
        self.environment_installer = environment_installer
        self.runner_path = Path(runner_path) if runner_path is not None else _runner_path()
        self.active_task: asyncio.Task | None = None
        self.process: asyncio.subprocess.Process | None = None
        self.install_cancel = threading.Event()
        self._status = "failed" if self._root_error else "idle"
        self._environment = {"ready": False, "missing": [], "reason": "not_checked"}
        self._error: str | None = "unsafe_output_root" if self._root_error else None
        self._progress: dict | None = None
        self._closing = False
        self._last_setting_signature: tuple | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending_settings_refresh = False

    def notify_settings_changed(self) -> None:
        """Let a settings write from FastAPI's worker thread wake this service."""
        loop = self._loop
        if loop is not None and loop.is_running() and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(self.refresh_on_settings_change)
            except RuntimeError:
                # Shutdown won the race; the next process start will scan.
                pass

    def refresh_on_settings_change(self) -> None:
        """A settings save followed by the UI status poll schedules a new scan."""
        if self._closing:
            return
        try:
            settings = self.settings_loader()
            signature = tuple(settings.get(key) for key in (
                "body_analysis_enabled", "body_analysis_leg_dir", "body_analysis_scalp_dir",
                "body_analysis_model_dir",
            ))
            active = self.active_task is not None and not self.active_task.done()
            if signature != self._last_setting_signature and active and self._last_setting_signature is not None:
                # The previous scan must not publish a superseded config. A
                # done callback resumes the latest settings even without UI
                # polling (for example a CLI settings update).
                if not self._pending_settings_refresh:
                    self._pending_settings_refresh = True
                    self.active_task.add_done_callback(self._resume_after_settings_change)
                self.install_cancel.set()
                self.active_task.cancel()
                if not settings.get("body_analysis_enabled"):
                    self._status = "disabled"
                    self._last_setting_signature = signature
            elif signature != self._last_setting_signature and not active:
                if self._root_error:
                    self._status, self._error = "failed", "unsafe_output_root"
                elif settings.get("body_analysis_enabled"):
                    if self.start():
                        self._last_setting_signature = signature
                else:
                    self._status = "disabled"
                    self._last_setting_signature = signature
        except Exception:
            self._status, self._error = "failed", "settings_unavailable"

    def _resume_after_settings_change(self, _finished: asyncio.Task) -> None:
        self._pending_settings_refresh = False
        self.refresh_on_settings_change()

    def _current(self) -> tuple[Path, dict, str] | None:
        if self.root is None:
            return None
        pointer = self.root / "current.json"
        try:
            if not pointer.is_file() or pointer.is_symlink() or pointer.stat().st_size > 4096:
                return None
            state = json.loads(pointer.read_text(encoding="utf-8"))
            name, fingerprint = state["directory"], state["fingerprint"]
            if not isinstance(name, str) or len(name) > 80 or not name.isascii() or not name.isalnum():
                return None
            if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
                return None
            folder = self.root / "published" / name
            if ((self.root / "published").is_symlink() or folder.is_symlink()
                    or not folder.is_dir() or not folder.resolve().is_relative_to(self.root.resolve())):
                return None
            report_path = folder / "report.json"
            if report_path.is_symlink() or report_path.stat().st_size > 50_000_000:
                return None
            report = json.loads(report_path.read_text(encoding="utf-8"))
            validate_report_manifest(report, folder)
            if _has_absolute_path(report):
                return None
            return folder, report, fingerprint
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None

    def report(self) -> dict | None:
        current = self._current()
        return current[1] if current else None

    def asset(self, relative: str) -> Path | None:
        current = self._current()
        if current is None or not isinstance(relative, str):
            return None
        folder, report, _ = current
        if "\\" in relative or ":" in relative or relative.startswith("/"):
            return None
        parsed = PurePosixPath(relative)
        if parsed.is_absolute() or ".." in parsed.parts or len(parsed.parts) < 2 or parsed.parts[0] not in {"masks", "overlays"}:
            return None
        if parsed.suffix.lower() not in ASSET_SUFFIXES or relative not in report["assets"]:
            return None
        target = folder.joinpath(*parsed.parts)
        try:
            if any(part.is_symlink() for part in (target, *target.parents) if part != folder):
                return None
            if target.is_file() and target.resolve().is_relative_to(folder.resolve()):
                return target
        except OSError:
            pass
        return None

    def status(self) -> dict:
        try:
            enabled = bool(self.settings_loader().get("body_analysis_enabled"))
        except Exception:
            enabled = False
            self._status, self._error = "failed", "settings_unavailable"
        result = {"status": self._status, "enabled": enabled,
                  "environment": {key: self._environment.get(key) for key in ("ready", "missing", "reason")},
                  "last_report_available": self._current() is not None}
        if self._error:
            result["error"] = self._error
        if self._progress:
            result["progress"] = dict(self._progress)
        return result

    def start(self, *, force: bool = False) -> bool:
        if self._root_error or self._closing or (self.active_task is not None and not self.active_task.done()):
            return False
        self._loop = asyncio.get_running_loop()
        self.active_task = asyncio.create_task(self._run(force=force))
        return True

    async def install(self) -> bool:
        if self._root_error or self._closing or (self.active_task is not None and not self.active_task.done()):
            return False
        self._loop = asyncio.get_running_loop()
        self.install_cancel = threading.Event()
        self.active_task = asyncio.create_task(self._install())
        return True

    async def _probe(self, model: Path) -> dict:
        # Blocking CPython probes belong off the backend event loop.
        if inspect.iscoroutinefunction(self.environment_probe):
            return await self.environment_probe(model)
        return await asyncio.to_thread(self.environment_probe, model)

    async def _install(self):
        self._status, self._error = "installing", None
        try:
            settings = await asyncio.to_thread(self.settings_loader)
            self._last_setting_signature = tuple(settings.get(key) for key in (
                "body_analysis_enabled", "body_analysis_leg_dir", "body_analysis_scalp_dir",
                "body_analysis_model_dir",
            ))
            paths = await asyncio.to_thread(validate_body_analysis_paths, settings)
            model = paths.get("body_analysis_model_dir")
            if not model:
                self._status = "missing_environment"
                self._environment = {"ready": False, "missing": ["model"], "reason": "missing_model"}
                return
            outcome = await asyncio.to_thread(
                self.environment_installer, model, explicit=True, cancel_event=self.install_cancel,
            )
            self._environment = _public_environment(outcome)
            if outcome.get("ready"):
                self._status = "idle"
                await self._run(force=False)
            else:
                self._status = "missing_environment" if outcome.get("state", "").startswith("missing") else "failed"
                self._error = None if self._status == "missing_environment" else "optional_install_failed"
        except asyncio.CancelledError:
            self.install_cancel.set()
            raise
        except Exception:
            self._status, self._error = "failed", "optional_install_failed"

    async def _run(self, *, force: bool):
        if self._root_error:
            self._status, self._error = "failed", "unsafe_output_root"
            return
        self._status, self._error, self._progress = "checking", None, None
        try:
            settings = await asyncio.to_thread(self.settings_loader)
            self._last_setting_signature = tuple(settings.get(key) for key in (
                "body_analysis_enabled", "body_analysis_leg_dir", "body_analysis_scalp_dir",
                "body_analysis_model_dir",
            ))
            if not settings.get("body_analysis_enabled"):
                self._status = "disabled"
                return
            configured = await asyncio.to_thread(validate_body_analysis_paths, settings)
            if any(not configured.get(f"body_analysis_{kind}_dir") for kind in ("leg", "scalp", "model")):
                self._status = "needs_setup"
                return
            paths = {kind: Path(configured[f"body_analysis_{kind}_dir"]) for kind in ("leg", "scalp", "model")}
            before = await asyncio.to_thread(source_snapshot, paths, self.runner_path)
            previous = await asyncio.to_thread(self._current)
            environment = await self._probe(paths["model"])
            self._environment = _public_environment(environment)
            if not environment.get("ready") or not environment.get("python_executable"):
                self._status = "missing_environment"
                return
            if not force and previous and previous[2] == before.fingerprint:
                self._status = "ready"
                return
            await self._generate(paths, before, str(environment["python_executable"]), self._last_setting_signature)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._status, self._error = "failed", "analysis_failed"

    async def _generate(self, paths: dict[str, Path], before: SourceSnapshot, python: str,
                        expected_settings: tuple) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        staging_root = self.root / "staging"
        published_root = self.root / "published"
        if staging_root.is_symlink() or published_root.is_symlink():
            raise ValueError("generated_storage_link_forbidden")
        staging_root.mkdir(exist_ok=True)
        published_root.mkdir(exist_ok=True)
        name = uuid.uuid4().hex
        output = staging_root / name
        progress_file = output / "progress.json"
        self._status = "running"
        self._progress = {"completed": 0, "total": sum(before.counts.values())}
        argv = [python, str(self.runner_path), "--leg-dir", str(paths["leg"]),
                "--scalp-dir", str(paths["scalp"]), "--model-dir", str(paths["model"]),
                "--staging-root", str(staging_root), "--output-dir", str(output),
                "--progress-json", str(progress_file)]
        try:
            self.process = await asyncio.create_subprocess_exec(
                *argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            while True:
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=0.4)
                    break
                except asyncio.TimeoutError:
                    self._read_progress(progress_file, before.counts)
            if self.process.returncode != 0:
                raise ValueError("runner_failed")
            report_file = output / "report.json"
            if report_file.is_symlink() or report_file.stat().st_size > 50_000_000:
                raise ValueError("report_unavailable")
            report = json.loads(report_file.read_text(encoding="utf-8"))
            validate_report_manifest(report, output)
            if _has_absolute_path(report):
                raise ValueError("private_path_in_report")
            if report["input_counts"] != before.counts:
                raise ValueError("source_count_changed")
            after = await asyncio.to_thread(source_snapshot, paths, self.runner_path)
            if after != before:
                raise ValueError("source_changed")
            latest_settings = await asyncio.to_thread(self.settings_loader)
            latest_signature = tuple(latest_settings.get(key) for key in (
                "body_analysis_enabled", "body_analysis_leg_dir", "body_analysis_scalp_dir",
                "body_analysis_model_dir",
            ))
            if latest_signature != expected_settings or not latest_settings.get("body_analysis_enabled"):
                raise ValueError("settings_changed")
            latest_paths = await asyncio.to_thread(validate_body_analysis_paths, latest_settings)
            if any(Path(latest_paths[f"body_analysis_{kind}_dir"]) != paths[kind] for kind in ("leg", "scalp", "model")):
                raise ValueError("settings_changed")
            destination = published_root / name
            os.replace(output, destination)
            _write_json_atomically(self.root / "current.json", {"directory": name, "fingerprint": before.fingerprint})
            self._status = "ready"
            self._progress = {"completed": sum(before.counts.values()), "total": sum(before.counts.values())}
        except asyncio.CancelledError:
            await self._stop_process()
            raise
        except Exception:
            self._status, self._error = "failed", "analysis_failed"
        finally:
            self.process = None
            if output.exists():
                try:
                    _discard_generated_staging(staging_root, output)
                except OSError:
                    pass

    def _read_progress(self, path: Path, counts: dict[str, int]) -> None:
        try:
            if path.is_symlink() or path.stat().st_size > 4096:
                return
            data = json.loads(path.read_text(encoding="utf-8"))
            total = sum(counts.values())
            completed = data.get("completed")
            if type(completed) is int and 0 <= completed <= total and data.get("total") == total:
                self._progress = {"completed": completed, "total": total}
        except (OSError, ValueError, TypeError):
            pass

    async def _stop_process(self) -> None:
        process = self.process
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

    async def close(self) -> None:
        self._closing = True
        self.install_cancel.set()
        task = self.active_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self._stop_process()

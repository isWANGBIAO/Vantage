"""Atomic publication of action-plan artifacts, separate from generation.

Only a verified, completely finished generation moves its result into the
history directory scanned by readers. Private staging directories are never
scanned, so a child/backend crash cannot make an unconfirmed plan visible after
restart. Usage databases keep their original location; chat context sidecars are
also staged and can only replace live contexts after a plan has been committed.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from src.services.action_plan_jobs import complete_plan, normalize_plan_date

LOGGER = logging.getLogger(__name__)
STAGING_ENV = "VANTAGE_ACTION_PLAN_STAGING_DIR"
STAGING_DIRECTORY = ".action-plan-staging"
MAX_PLAN_BYTES = 32 * 1024 * 1024
CONTEXT_FILENAMES = (
    "latest_context.json", "latest_context_session.json",
    "latest_action_plan_context.json", "latest_action_plan_context_session.json",
)
_PLAN_NAME = re.compile(r"^action_plan_(\d{8})_.+\.json$")


@dataclass(frozen=True)
class PendingActionPlan:
    directory: Path
    previous_files: tuple[Path, ...]

    @property
    def output_file(self) -> Path:
        return self.directory / "action_plan.json"


@dataclass(frozen=True)
class PublishedActionPlan:
    path: Path
    context_updated: bool


class ActionPlanStore:
    def __init__(self, history_dir: str | Path, *, today: Callable[[], str] | None = None):
        self.history_dir = Path(history_dir).resolve()
        self._staging_root = self.history_dir / STAGING_DIRECTORY
        self._today = today or (lambda: date.today().isoformat())

    def begin(self) -> PendingActionPlan:
        self.history_dir.mkdir(parents=True, exist_ok=True)
        if self._staging_root.is_symlink():
            raise ValueError("Action-plan staging root must not be a symbolic link")
        self._staging_root.mkdir(mode=0o700, exist_ok=True)
        directory = self._staging_root / uuid.uuid4().hex
        directory.mkdir(mode=0o700)
        previous = tuple(path for path in self.history_dir.glob("action_plan_*.json") if path.is_file())
        return PendingActionPlan(directory, previous)

    def _check_owned(self, pending: PendingActionPlan):
        # Never clean/publish an arbitrary path supplied by a caller or symlink.
        directory = pending.directory
        if self._staging_root.is_symlink() or directory.is_symlink() or directory.parent != self._staging_root:
            raise ValueError("Invalid action-plan staging directory")
        if directory.resolve().parent != self._staging_root.resolve():
            raise ValueError("Invalid action-plan staging directory")
        if not re.fullmatch(r"[0-9a-f]{32}", directory.name):
            raise ValueError("Invalid action-plan staging directory")

    @staticmethod
    def _read_json(path: Path):
        if path.is_symlink():
            raise ValueError("Staged action-plan artifacts must be regular files")
        with path.open("rb") as handle:
            content = handle.read(MAX_PLAN_BYTES + 1)
            if len(content) > MAX_PLAN_BYTES:
                raise ValueError("Staged action-plan artifact exceeds the size limit")
        return json.loads(content)

    def publish(self, pending: PendingActionPlan, *, replace_today: bool = False) -> PublishedActionPlan:
        """Commit once after the raw stream exits successfully with done=true.

        All validation occurs before the atomic rename. Failures after commit
        (context refresh or requested old-file cleanup) are recoverable ancillary
        errors, never a failed generation that exposes a newly saved result.
        """
        self._check_owned(pending)
        try:
            payload = self._read_json(pending.output_file)
        except (OSError, ValueError, UnicodeError) as exc:
            raise RuntimeError("Generation did not save a new complete plan") from exc
        if not complete_plan(payload):
            raise RuntimeError("Generation did not save a new complete plan")
        plan_date = normalize_plan_date(payload.get("date"))
        if plan_date is None or plan_date != normalize_plan_date(self._today()):
            raise RuntimeError("Generated action plan belongs to a different day; retry for today")

        contexts = []
        for filename in CONTEXT_FILENAMES:
            path = pending.directory / filename
            if not path.exists():
                continue
            content = self._read_json(path)
            expected_type = dict if filename.endswith("_session.json") else list
            if not isinstance(content, expected_type):
                raise ValueError("Staged action-plan context has an invalid format")
            contexts.append(path)

        # Distinct filenames prevent same-second generations overwriting a valid
        # plan. A future-dated legacy mtime also cannot hide the newly committed one.
        previous_times = [
            path.stat().st_mtime_ns for path in self.history_dir.glob(f"action_plan_{plan_date}_*.json")
            if path.is_file()
        ]
        # Two seconds also covers legacy filesystems with coarse timestamp
        # resolution; a +1 ns increment can round back to the old timestamp.
        published_at = max(time.time_ns(), max(previous_times, default=0) + 2_000_000_000)
        os.utime(pending.output_file, ns=(published_at, published_at))
        # Windows FlushFileBuffers requires a writable handle.
        with pending.output_file.open("rb+") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        target = self.history_dir / f"action_plan_{plan_date}_{pending.directory.name}.json"
        os.replace(pending.output_file, target)
        # From this point onward the valid plan is committed. Do not report a
        # failed generation merely because an optional follow-up file is locked.
        context_updated = len(contexts) == len(CONTEXT_FILENAMES)
        if not context_updated:
            LOGGER.warning("Published plan, but some chat context files were not produced")
        for path in contexts:
            try:
                os.replace(path, self.history_dir / path.name)
            except OSError:
                context_updated = False
                LOGGER.warning("Published plan, but a chat context file could not be refreshed")
        if replace_today:
            for path in pending.previous_files:
                match = _PLAN_NAME.fullmatch(path.name)
                if not match or match.group(1) != plan_date:
                    continue
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    LOGGER.warning("Published plan, but an older plan file could not be removed")
        return PublishedActionPlan(target, context_updated)

    def discard(self, pending: PendingActionPlan):
        """Remove only this invocation's staging files; never touch live data."""
        self._check_owned(pending)
        try:
            shutil.rmtree(pending.directory)
        except FileNotFoundError:
            pass
        except OSError:
            LOGGER.warning("An action-plan staging directory could not be removed")

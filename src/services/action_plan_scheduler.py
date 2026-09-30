"""Backend-owned action-plan startup and source-change scheduling.

Only dates and SHA-256 digests are persisted. Settings, prompts, credentials,
stream events and plan bodies never enter the scheduler metadata file.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import math
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

from .action_plan_jobs import (
    ActionPlanJobService, call_callback, complete_plan, normalize_plan_date, plan_identity,
)

LOGGER = logging.getLogger(__name__)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_METADATA_BYTES = 4096
_MAX_INTERVAL_MINUTES = 2_147_483_647 // 60_000


def _revision_digest(revision: str) -> str:
    # Even a buggy adapter cannot accidentally persist arbitrary source text.
    return hashlib.sha256(revision.encode("utf-8")).hexdigest()


def _empty_state(date: str) -> dict:
    return {"version": 1, "date": date, "baseline_revision": None,
            "generated_revision": None, "generated_plan_identity": None}


class ActionPlanScheduler:
    """Start once from the backend lifespan and close on backend shutdown.

    ``action_plan_auto_generate`` controls a missing plan at startup/day change.
    ``action_plan_check_interval_minutes`` independently controls revision checks;
    zero disables those checks only. No generation occurs until onboarding is
    complete. Failed runs never advance the last successfully consumed revision.
    ``tick`` is public to permit deterministic, injected async tests.
    """

    def __init__(
        self,
        jobs: ActionPlanJobService,
        read_settings: Callable,
        read_today: Callable,
        read_revision: Callable,
        metadata_path: str | Path,
        *,
        poll_seconds: float = 1.0,
        today: Callable[[], str] = lambda: datetime.now().strftime("%Y%m%d"),
        monotonic: Callable[[], float] = time.monotonic,
    ):
        if not math.isfinite(poll_seconds) or poll_seconds <= 0:
            raise ValueError("Scheduler polling interval must be positive")
        self._jobs = jobs
        self._read_settings = read_settings
        self._read_today = read_today
        self._read_revision = read_revision
        self._metadata_path = Path(metadata_path)
        self._poll_seconds = poll_seconds
        self._today = today
        self._monotonic = monotonic
        self._state = _empty_state(self._current_date())
        self._loaded = False
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._closed = False
        self._wake = asyncio.Event()
        self._interval: int | None = None
        self._next_check = 0.0
        self._startup_handled = False
        self._startup_retry_at = 0.0
        self._last_error: dict | None = None
        self._last_outcome = "idle"
        self._startup_enabled = False
        self._onboarding_complete = False
        self._pending_success_state: dict | None = None
        self._remove_listener = jobs.add_completion_listener(self._on_completed)

    def _current_date(self) -> str:
        date = normalize_plan_date(self._today())
        if date is None:
            raise ValueError("Scheduler date must be a valid YYYYMMDD or YYYY-MM-DD date")
        return date

    def start(self):
        if self._closed:
            raise RuntimeError("Action plan scheduler is closed")
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="action-plan-scheduler")
        return self._task

    async def close(self):
        self._closed = True
        self._wake.set()
        if self._task is not None:
            # Let any metadata atomic write finish instead of cancelling to_thread.
            await asyncio.shield(self._task)
        self._remove_listener()

    def status(self) -> dict:
        return {"running": bool(self._task and not self._task.done()),
                "enabled": self._onboarding_complete and (self._startup_enabled or bool(self._interval)),
                "startup_auto_generate": self._startup_enabled,
                "onboarding_completed": self._onboarding_complete,
                "outcome": self._last_outcome, "error": copy.deepcopy(self._last_error),
                "check_interval_minutes": self._interval,
                "date": self._state["date"],
                "baseline_revision": self._state["baseline_revision"],
                "generated_revision": self._state["generated_revision"]}

    async def _run(self):
        while not self._closed:
            self._wake.clear()
            await self.tick()
            if self._closed:
                break
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._poll_seconds)
            except asyncio.TimeoutError:
                pass

    def _read_metadata(self) -> dict | None:
        try:
            with self._metadata_path.open("rb") as handle:
                data = handle.read(_MAX_METADATA_BYTES + 1)
            if len(data) > _MAX_METADATA_BYTES:
                return None
            value = json.loads(data)
            if not isinstance(value, dict) or value.get("version") != 1:
                return None
            date = normalize_plan_date(value.get("date"))
            if date is None:
                return None
            result = _empty_state(date)
            for key in ("baseline_revision", "generated_revision", "generated_plan_identity"):
                digest = value.get(key)
                if digest is not None and (not isinstance(digest, str) or not _DIGEST.fullmatch(digest)):
                    return None
                result[key] = digest
            return result
        except FileNotFoundError:
            return None
        except (OSError, ValueError, UnicodeError):
            self._last_error = {"code": "metadata_read_failed", "message": "调度记录暂不可用。"}
            return None

    def _write_metadata(self, state: dict):
        self._metadata_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".action-plan-", suffix=".tmp",
                                         dir=self._metadata_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=True, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._metadata_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    async def _load(self):
        date = self._current_date()
        if not self._loaded:
            value = await asyncio.to_thread(self._read_metadata)
            if value and value["date"] == date:
                self._state = value
            self._loaded = True
        if self._state["date"] != date:
            self._state = _empty_state(date)
            self._startup_handled = False
            self._startup_retry_at = 0.0
            self._next_check = 0.0
            self._pending_success_state = None

    async def _persist(self, state: dict) -> bool:
        try:
            await asyncio.to_thread(self._write_metadata, state)
        except OSError:
            self._last_error = {"code": "metadata_write_failed", "message": "调度记录未能保存。"}
            return False
        self._state = state
        return True

    async def _on_completed(self, job: dict):
        if job.get("status") != "succeeded" or not complete_plan(job.get("result")):
            self._wake.set()
            return
        revision = job.get("source_revision")
        if not isinstance(revision, str) or not revision.strip():
            return
        async with self._lock:
            await self._load()
            result = job["result"]
            # A run finishing across midnight must not certify yesterday's plan.
            result_date = normalize_plan_date(result.get("date"))
            if result_date != self._current_date():
                self._wake.set()
                return
            digest = _revision_digest(revision)
            state = {**self._state, "baseline_revision": digest,
                     "generated_revision": digest,
                     "generated_plan_identity": plan_identity(result)}
            self._pending_success_state = state
            if await self._persist(state):
                self._pending_success_state = None
                self._startup_handled = True
                self._last_error = None
            self._wake.set()

    @staticmethod
    def _get_interval(settings: Mapping) -> int:
        value = settings.get("action_plan_check_interval_minutes", 60)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return 60
        return min(value, _MAX_INTERVAL_MINUTES)

    async def tick(self, *, force_check: bool = False) -> dict:
        async with self._lock:
            if self._closed:
                return {"outcome": "closed"}
            try:
                outcome = await self._tick(force_check=force_check)
            except Exception as exc:
                # Keep scheduling alive, but never expose adapter exceptions/paths.
                LOGGER.warning("Action plan scheduler tick failed (%s)", type(exc).__name__)
                self._last_error = {"code": "scheduler_unavailable", "message": "自动生成暂不可用，将稍后重试。"}
                outcome = {"outcome": "unavailable"}
            self._last_outcome = outcome["outcome"]
            return outcome

    async def _tick(self, *, force_check: bool) -> dict:
        await self._load()
        if self._pending_success_state is not None:
            if not await self._persist(self._pending_success_state):
                return {"outcome": "metadata_unavailable"}
            self._pending_success_state = None
            self._startup_handled = True
            self._last_error = None
        settings = await call_callback(self._read_settings)
        if not isinstance(settings, Mapping):
            return {"outcome": "settings_unavailable"}
        now = self._monotonic()
        interval = self._get_interval(settings)
        if interval != self._interval:
            self._next_check = 0.0 if self._interval is None else now + interval * 60
            self._interval = interval
        self._startup_enabled = settings.get("action_plan_auto_generate", True) is True
        self._onboarding_complete = settings.get("onboarding_completed") is True
        if not self._onboarding_complete:
            return {"outcome": "awaiting_onboarding"}
        active = self._jobs.active()
        if active is not None:
            return {"outcome": "busy", "job_id": active["id"]}
        startup_enabled = self._startup_enabled
        startup_due = startup_enabled and not self._startup_handled and now >= self._startup_retry_at
        check_due = interval > 0 and (force_check or now >= self._next_check)
        if not startup_due and not check_due:
            return {"outcome": "idle"}
        if check_due:
            self._next_check = now + interval * 60
        today_plan = await call_callback(self._read_today)
        if not isinstance(today_plan, Mapping) or today_plan.get("error"):
            self._startup_retry_at = now + max(5.0, self._poll_seconds)
            self._last_error = {"code": "plan_read_failed", "message": "无法读取已保存的行动计划。"}
            return {"outcome": "plan_unavailable"}
        plan_date = normalize_plan_date(today_plan.get("date"))
        if today_plan.get("exists") is not False and plan_date is None:
            self._startup_retry_at = now + max(5.0, self._poll_seconds)
            self._last_error = {"code": "invalid_plan_date", "message": "已保存行动计划的日期无效。"}
            return {"outcome": "plan_unavailable"}
        has_plan = complete_plan(today_plan) and plan_date == self._current_date()
        if startup_due and has_plan:
            self._startup_handled = True
            startup_due = False
        if not startup_due and not check_due:
            return {"outcome": "plan_exists"}
        try:
            revision = await call_callback(self._read_revision)
            if not isinstance(revision, str) or not revision.strip():
                raise ValueError("Empty revision")
        except Exception:
            self._startup_retry_at = now + max(5.0, self._poll_seconds)
            self._last_error = {"code": "source_unavailable", "message": "行动计划数据源暂不可用。"}
            return {"outcome": "source_unavailable"}
        digest = _revision_digest(revision)
        if startup_due and not has_plan:
            return await self._start_job("startup", now, interval)
        baseline = self._state["baseline_revision"]
        if baseline is None:
            if startup_enabled and self._startup_handled and not has_plan:
                # Retry a failed startup on the configured interval. Never record
                # its unconsumed revision as a successful baseline.
                return await self._start_job("startup", now, interval)
            saved = await self._persist({**self._state, "baseline_revision": digest})
            return {"outcome": "baseline_recorded" if saved else "metadata_unavailable"}
        if digest == baseline:
            self._last_error = None
            return {"outcome": "unchanged"}
        return await self._start_job("source_changed", now, interval)

    async def _start_job(self, trigger: str, now: float, interval: int) -> dict:
        job = await self._jobs.start({"replace_today": True,
                                      "wait_for_provider_ready": trigger == "startup"},
                                     trigger=trigger)
        if not job["reused"]:
            if trigger == "startup":
                self._startup_handled = True
            self._next_check = now + interval * 60
        return {"outcome": "busy" if job["reused"] else "started",
                "job_id": job["id"], "trigger": job["trigger"]}

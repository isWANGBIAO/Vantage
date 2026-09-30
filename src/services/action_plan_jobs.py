"""Transport-independent, single-flight action-plan jobs.

The injected generator owns subprocess termination/reaping in its ``finally``
block. HTTP readers only subscribe to events; cancelling a reader never cancels
its job. Events and result bodies are kept in bounded/retained memory only.
"""

from __future__ import annotations

import asyncio
import codecs
import copy
import hashlib
import inspect
import json
import logging
import re
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

LOGGER = logging.getLogger(__name__)
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
REQUEST_FIELDS = frozenset({
    "model", "provider_route", "reasoning_effort", "service_tier",
    "replace_today", "wait_for_provider_ready",
})
_ERROR_PREFIXES = ("STREAM_ANALYSIS_ERROR:", "STREAM_PLAN_ERROR:", "STREAM_ERROR:")


async def call_callback(callback: Callable, *args):
    """Accept sync or async dependency adapters without blocking the event loop."""
    if inspect.iscoroutinefunction(callback) or inspect.isasyncgenfunction(callback):
        value = callback(*args)
    else:
        value = await asyncio.to_thread(callback, *args)
    return await value if inspect.isawaitable(value) else value


def normalize_plan_date(value: Any) -> str | None:
    """Normalize a valid persisted/API date without mutating its source payload."""
    if not isinstance(value, str):
        return None
    if re.fullmatch(r"[0-9]{8}", value):
        date_format = "%Y%m%d"
    elif re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        date_format = "%Y-%m-%d"
    else:
        return None
    try:
        parsed = datetime.strptime(value, date_format)
        return f"{parsed.year:04d}{parsed.month:02d}{parsed.day:02d}"
    except ValueError:
        return None


def complete_plan(payload: Any) -> bool:
    """A partial/failed save is never a successful action-plan result."""
    if not isinstance(payload, Mapping) or payload.get("exists") is False or payload.get("error"):
        return False
    if "date" in payload and normalize_plan_date(payload["date"]) is None:
        return False
    for section in ("analysis", "plan"):
        value = payload.get(section)
        if not isinstance(value, Mapping) or not isinstance(value.get("body"), str):
            return False
        if not value["body"].strip():
            return False
    return True


def plan_identity(payload: Any) -> str | None:
    """Opaque identity: no content, filenames or personal data leave this hash."""
    if not isinstance(payload, Mapping) or payload.get("exists") is False:
        return None
    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class _JobFailure(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class _Job:
    id: str
    request: dict
    trigger: str
    created_at: str
    updated_at: str
    status: str = "queued"
    progress: dict = field(default_factory=lambda: {"phase": "queued", "events_received": 0})
    result: dict | None = None
    error: dict | None = None
    source_revision: str | None = None
    result_identity: str | None = None
    events: deque = field(default_factory=deque)
    event_bytes: int = 0
    sequence: int = 0
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    cancellation_requested: bool = False


class ActionPlanJobService:
    """One instance per backend lifespan; all UI and scheduler starts share it.

    ``generate(request)`` returns (or resolves to) an async NDJSON iterator.
    ``read_today()`` returns the persisted plan API payload, including a stable
    id or filename when possible. ``read_revision()`` returns a source digest.
    The iterator must exhaust and emit ``{"done": true}`` before a *new*,
    complete persisted plan can mark a job successful.
    """

    def __init__(
        self,
        generate: Callable,
        read_today: Callable,
        read_revision: Callable | None = None,
        *,
        event_limit: int = 256,
        event_buffer_bytes: int = 2 * 1024 * 1024,
        retained_jobs: int = 32,
        max_stream_line_bytes: int = 1024 * 1024,
        now: Callable[[], float] = time.time,
    ):
        if min(event_limit, event_buffer_bytes, retained_jobs, max_stream_line_bytes) < 1:
            raise ValueError("Job retention and stream limits must be positive")
        self._generate = generate
        self._read_today = read_today
        self._read_revision = read_revision
        self._event_limit = event_limit
        self._event_buffer_bytes = event_buffer_bytes
        self._retained_jobs = retained_jobs
        self._max_stream_line_bytes = max_stream_line_bytes
        self._now = now
        self._jobs: dict[str, _Job] = {}
        self._active_id: str | None = None
        self._lock = asyncio.Lock()
        self._closed = False
        self._listeners: list[Callable] = []

    def _timestamp(self) -> str:
        return datetime.fromtimestamp(self._now(), timezone.utc).isoformat()

    def add_completion_listener(self, callback: Callable) -> Callable[[], None]:
        self._listeners.append(callback)

        def remove():
            if callback in self._listeners:
                self._listeners.remove(callback)

        return remove

    def _snapshot(self, job: _Job) -> dict:
        return copy.deepcopy({
            "id": job.id, "status": job.status, "trigger": job.trigger,
            "request": job.request, "created_at": job.created_at,
            "updated_at": job.updated_at, "progress": job.progress,
            "result": job.result, "error": job.error,
            "source_revision": job.source_revision,
            "result_identity": job.result_identity, "event_cursor": job.sequence,
        })

    def get(self, job_id: str) -> dict:
        return self._snapshot(self._jobs[job_id])

    def active(self) -> dict | None:
        job = self._jobs.get(self._active_id)
        return self._snapshot(job) if job else None

    def list_jobs(self) -> list[dict]:
        return [self._snapshot(job) for job in reversed(list(self._jobs.values()))]

    async def start(self, request: Mapping | None = None, *, trigger: str = "manual") -> dict:
        async with self._lock:
            if self._closed:
                raise RuntimeError("Action plan job service is closed")
            current = self.active()
            if current:
                return {**current, "reused": True}
            parameters = {key: copy.deepcopy(value) for key, value in (request or {}).items()
                          if key in REQUEST_FIELDS}
            timestamp = self._timestamp()
            job = _Job(uuid.uuid4().hex, parameters, str(trigger), timestamp, timestamp)
            self._jobs[job.id] = job
            self._active_id = job.id
            self._append(job, {"job_status": "queued"})
            job.task = asyncio.create_task(self._run(job), name=f"action-plan-{job.id}")
            job.task.add_done_callback(lambda task: self._task_finished(job, task))
            self._prune()
            return {**self._snapshot(job), "reused": False}

    def _task_finished(self, job: _Job, task: asyncio.Task):
        # Cancellation before the coroutine starts has no finally block. This
        # callback also finalizes it if the cancelling HTTP request disconnects.
        if task.cancelled() and job.status not in TERMINAL_STATUSES:
            self._mark_cancelled(job)
            if self._active_id == job.id:
                self._active_id = None

    def _prune(self):
        for job_id in list(self._jobs):
            if len(self._jobs) <= self._retained_jobs:
                break
            job = self._jobs[job_id]
            if job.status in TERMINAL_STATUSES and (job.task is None or job.task.done()):
                del self._jobs[job_id]

    def _append(self, job: _Job, payload: dict):
        job.sequence += 1
        job.updated_at = self._timestamp()
        event = {**copy.deepcopy(payload), "sequence": job.sequence, "timestamp": job.updated_at}
        size = len(json.dumps(event, ensure_ascii=False, default=str).encode("utf-8"))
        if size > self._event_buffer_bytes:
            event = {"sequence": job.sequence, "event_truncated": True, "truncated": True,
                     "timestamp": job.updated_at}
            size = len(json.dumps(event).encode("utf-8"))
        # An exceptionally small configured byte limit can hold no event.
        if size <= self._event_buffer_bytes:
            job.events.append((event, size))
            job.event_bytes += size
        while job.events and (len(job.events) > self._event_limit
                              or job.event_bytes > self._event_buffer_bytes):
            _, dropped_size = job.events.popleft()
            job.event_bytes -= dropped_size
        changed, job.changed = job.changed, asyncio.Event()
        changed.set()

    def events(self, job_id: str, after: int = 0) -> dict:
        return self._events_for(self._jobs[job_id], after)

    def _events_for(self, job: _Job, after: int) -> dict:
        cursor = max(0, int(after))
        first = job.events[0][0]["sequence"] if job.events else job.sequence + 1
        return {
            "events": copy.deepcopy([event for event, _ in job.events if event["sequence"] > cursor]),
            "cursor": job.sequence,
            "truncated": cursor < first - 1,
            "job": self._snapshot(job),
        }

    async def iterate_events(self, job_id: str, after: int = 0) -> AsyncIterator[dict]:
        """Subscribe without owning the job, replaying a bounded cursor window."""
        job = self._jobs[job_id]
        cursor = max(0, int(after))
        while True:
            changed = job.changed
            batch = self._events_for(job, cursor)
            if batch["truncated"]:
                yield {"truncated": True, "cursor": batch["cursor"],
                       "job_status": batch["job"]["status"]}
            for event in batch["events"]:
                cursor = event["sequence"]
                yield event
            cursor = max(cursor, batch["cursor"])
            if batch["job"]["status"] in TERMINAL_STATUSES:
                return
            await changed.wait()

    async def wait(self, job_id: str) -> dict:
        job = self._jobs[job_id]
        if job.task:
            try:
                await asyncio.shield(job.task)
            except asyncio.CancelledError:
                if not job.task.cancelled():
                    raise
        return self._snapshot(job)

    async def cancel(self, job_id: str) -> dict:
        job = self._jobs[job_id]
        if job.status in TERMINAL_STATUSES:
            return self._snapshot(job)
        if not job.cancellation_requested:
            job.cancellation_requested = True
            job.status = "cancelling"
            job.progress["phase"] = "cancelling"
            self._append(job, {"job_status": "cancelling"})
            if job.task:
                job.task.cancel()
        if job.task:
            try:
                await asyncio.shield(job.task)
            except asyncio.CancelledError:
                # A task cancelled before its first instruction has no finally.
                if not job.task.done():
                    raise
        if job.status not in TERMINAL_STATUSES:
            self._mark_cancelled(job)
            if self._active_id == job.id:
                self._active_id = None
        return self._snapshot(job)

    async def close(self):
        async with self._lock:
            self._closed = True
        active = self.active()
        if active:
            await self.cancel(active["id"])
        tasks = [job.task for job in self._jobs.values() if job.task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _mark_cancelled(self, job: _Job):
        job.status = "cancelled"
        job.progress["phase"] = "cancelled"
        self._append(job, {"job_status": "cancelled", "cancelled": True})

    async def _read_plan(self) -> dict:
        try:
            payload = await call_callback(self._read_today)
        except Exception as exc:
            raise _JobFailure("plan_read_failed", "无法读取已保存的行动计划。") from exc
        if not isinstance(payload, Mapping) or payload.get("error"):
            raise _JobFailure("plan_read_failed", "无法读取已保存的行动计划。")
        return dict(payload)

    async def _decoded_events(self, iterator) -> AsyncIterator[dict]:
        decoder = codecs.getincrementaldecoder("utf-8")()
        pending = ""
        async for chunk in iterator:
            if isinstance(chunk, Mapping):
                if pending.strip():
                    raise _JobFailure("invalid_stream", "行动计划输出格式不完整。")
                yield dict(chunk)
                continue
            if not isinstance(chunk, (str, bytes)):
                raise _JobFailure("invalid_stream", "行动计划输出格式无效。")
            pending += decoder.decode(chunk) if isinstance(chunk, bytes) else chunk
            while "\n" in pending:
                line, pending = pending.split("\n", 1)
                if line.strip():
                    yield self._parse_event(line)
            if len(pending.encode("utf-8")) > self._max_stream_line_bytes:
                raise _JobFailure("invalid_stream", "行动计划输出超出缓冲限制。")
        pending += decoder.decode(b"", final=True)
        if pending.strip():
            yield self._parse_event(pending)

    def _parse_event(self, line: str) -> dict:
        if len(line.encode("utf-8")) > self._max_stream_line_bytes:
            raise _JobFailure("invalid_stream", "行动计划输出超出缓冲限制。")
        try:
            payload = json.loads(line)
        except (ValueError, TypeError) as exc:
            raise _JobFailure("invalid_stream", "行动计划输出格式无效。") from exc
        if not isinstance(payload, dict):
            raise _JobFailure("invalid_stream", "行动计划输出格式无效。")
        return payload

    async def _run(self, job: _Job):
        iterator = None
        try:
            job.status = "running"
            job.progress["phase"] = "starting"
            self._append(job, {"job_status": "running"})
            before = await self._read_plan()
            if self._read_revision is not None:
                try:
                    revision = await call_callback(self._read_revision)
                    if not isinstance(revision, str) or not revision.strip():
                        raise ValueError("Empty source revision")
                    job.source_revision = revision
                except Exception as exc:
                    raise _JobFailure("source_unavailable", "行动计划数据源暂不可用。") from exc
            iterator = await call_callback(self._generate, copy.deepcopy(job.request))
            saw_done = False
            saw_error = False
            async for event in self._decoded_events(iterator):
                job.progress["events_received"] += 1
                log = event.get("log")
                if "error" in event or (isinstance(log, str) and log.startswith(_ERROR_PREFIXES)):
                    saw_error = True
                if isinstance(log, str):
                    if log.startswith("STREAM_PLAN_"):
                        job.progress["phase"] = "plan"
                    elif log.startswith("STREAM_ANALYSIS_"):
                        job.progress["phase"] = "analysis"
                if event.get("done") is True:
                    saw_done = True
                    event = {key: value for key, value in event.items() if key != "done"}
                if event:
                    self._append(job, event)
            # Exhaustion includes the generator's subprocess exit/cleanup check.
            if saw_error:
                raise _JobFailure("generation_failed", "行动计划生成失败，请检查服务日志。")
            if not saw_done:
                raise _JobFailure("missing_done", "行动计划生成未确认完成。")
            job.progress["phase"] = "persisting"
            self._append(job, {"job_status": "running", "phase": "persisting"})
            result = await self._read_plan()
            if not complete_plan(result):
                raise _JobFailure("incomplete_result", "生成结果未完整保存，请重试。")
            identity = plan_identity(result)
            if identity == plan_identity(before):
                raise _JobFailure("result_not_saved", "未找到本次生成的新行动计划。")
            job.result = copy.deepcopy(result)
            job.result_identity = identity
            job.status = "succeeded"
            job.progress["phase"] = "complete"
            self._append(job, {"done": True, "job_status": "succeeded"})
        except asyncio.CancelledError:
            self._mark_cancelled(job)
        except Exception as exc:
            job.status = "failed"
            job.progress["phase"] = "failed"
            if isinstance(exc, _JobFailure):
                job.error = {"code": exc.code, "message": exc.message}
            else:
                job.error = {"code": "generation_failed", "message": "行动计划生成失败，请检查服务日志。"}
                LOGGER.warning("Action plan job failed (%s)", type(exc).__name__)
            self._append(job, {"error": job.error["message"], "error_code": job.error["code"],
                               "job_status": "failed"})
        finally:
            if iterator is not None and callable(getattr(iterator, "aclose", None)):
                try:
                    await iterator.aclose()
                except Exception as exc:
                    LOGGER.warning("Action plan iterator cleanup failed (%s)", type(exc).__name__)
            for listener in tuple(self._listeners):
                try:
                    await call_callback(listener, self._snapshot(job))
                except Exception as exc:
                    LOGGER.warning("Action plan completion listener failed (%s)", type(exc).__name__)
            if self._active_id == job.id:
                self._active_id = None
            job.changed.set()

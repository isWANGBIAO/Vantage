import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from src.core.config import Config


def _now():
    return datetime.now().astimezone()


def _isoformat(value=None):
    current = value or _now()
    return current.isoformat(timespec="seconds")


def _filename_timestamp(value=None):
    current = value or _now()
    return current.strftime("%Y-%m-%dT%H-%M-%S")


def _sanitize_filename(value):
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(value))


def _db_path(history_dir):
    return Path(history_dir) / "state.db"


def _sessions_root(history_dir):
    return Path(history_dir) / "sessions"


def _connect(db_file):
    path = Path(db_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    return conn


@contextmanager
def _open_db(db_file):
    conn = _connect(db_file)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_db(db_file):
    with _open_db(db_file) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source TEXT NOT NULL,
                entrypoint TEXT,
                cwd TEXT,
                context_file TEXT,
                default_model TEXT,
                provider_route TEXT,
                base_url TEXT,
                rollout_path TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS model_calls (
                call_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                model TEXT,
                provider_route TEXT,
                reasoning_effort TEXT,
                stream INTEGER NOT NULL,
                duration REAL,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                total_tokens INTEGER,
                error_type TEXT,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS session_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                call_id TEXT NOT NULL,
                message_index INTEGER NOT NULL,
                role TEXT NOT NULL,
                content_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_model_calls_session_id
            ON model_calls (session_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_session_messages_lookup
            ON session_messages (session_id, call_id, message_index);
            """
        )


def _normalize_usage(usage):
    usage = usage or {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }


def get_session_usage_summary(session_id, db_file=None):
    resolved_db_file = Path(db_file) if db_file else _db_path(Config.get_history_dir())
    _ensure_db(resolved_db_file)

    with _open_db(resolved_db_file) as conn:
        row = conn.execute(
            """
            SELECT
                s.session_id,
                s.source,
                s.entrypoint,
                s.default_model,
                s.provider_route,
                s.base_url,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.prompt_tokens, 0) ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.completion_tokens, 0) ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.total_tokens, 0) ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.duration, 0) ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN 1 ELSE 0 END), 0)
            FROM sessions s
            LEFT JOIN model_calls mc
                ON s.session_id = mc.session_id
            WHERE s.session_id = ?
            GROUP BY
                s.session_id,
                s.source,
                s.entrypoint,
                s.default_model,
                s.provider_route,
                s.base_url
            """,
            (session_id,),
        ).fetchone()

    if row is None:
        return None

    (
        session_id_value,
        source,
        entrypoint,
        default_model,
        provider_route,
        base_url,
        prompt_tokens,
        completion_tokens,
        total_tokens,
        total_duration,
        call_count,
    ) = row

    average_duration = float(total_duration) / int(call_count) if call_count else 0.0
    return {
        "session_id": session_id_value,
        "source": source,
        "entrypoint": entrypoint,
        "default_model": default_model,
        "provider_route": provider_route,
        "base_url": base_url,
        "call_count": int(call_count),
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "total_tokens": int(total_tokens),
        "total_duration": float(total_duration),
        "average_duration": average_duration,
    }


def get_usage_dashboard_snapshot(db_file=None, *, day_limit=14, session_limit=10, call_limit=20):
    resolved_db_file = Path(db_file) if db_file else _db_path(Config.get_history_dir())
    _ensure_db(resolved_db_file)

    def _as_int(value):
        return int(value or 0)

    def _as_float(value):
        return float(value or 0.0)

    def _build_usage_row(row):
        keys = set(row.keys())
        payload = {key: row[key] for key in row.keys()}
        completed = _as_int(payload["completed_call_count"]) if "completed_call_count" in keys else (1 if payload.get("status") == "completed" else 0)
        total_duration = _as_float(payload["total_duration"]) if "total_duration" in keys else _as_float(payload.get("duration"))
        total_tokens = _as_int(payload["total_tokens"])
        payload["session_count"] = _as_int(payload.get("session_count"))
        payload["call_count"] = _as_int(payload.get("call_count")) if "call_count" in keys else 1
        payload["completed_call_count"] = completed
        payload["failed_call_count"] = _as_int(payload.get("failed_call_count")) if "failed_call_count" in keys else (1 if payload.get("status") == "failed" else 0)
        payload["prompt_tokens"] = _as_int(payload.get("prompt_tokens"))
        payload["completion_tokens"] = _as_int(payload.get("completion_tokens"))
        payload["total_tokens"] = total_tokens
        payload["total_duration"] = total_duration
        payload["average_duration"] = (total_duration / completed) if completed else 0.0
        payload["average_tokens_per_call"] = (total_tokens / completed) if completed else 0.0
        payload["average_tokens_per_second"] = (total_tokens / total_duration) if total_duration else 0.0
        if "stream" in payload:
            payload["stream"] = bool(payload["stream"]) if payload["stream"] is not None else None
        return payload

    with _open_db(resolved_db_file) as conn:
        conn.row_factory = sqlite3.Row

        summary_row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM sessions) AS session_count,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_call_count,
                COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_call_count,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN COALESCE(prompt_tokens, 0) ELSE 0 END), 0) AS prompt_tokens,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN COALESCE(completion_tokens, 0) ELSE 0 END), 0) AS completion_tokens,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN COALESCE(total_tokens, 0) ELSE 0 END), 0) AS total_tokens,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN COALESCE(duration, 0) ELSE 0 END), 0) AS total_duration,
                MIN(created_at) AS earliest_call_at,
                MAX(COALESCE(completed_at, created_at)) AS latest_call_at
            FROM model_calls
            """
        ).fetchone()

        source_rows = conn.execute(
            """
            SELECT
                s.source,
                COUNT(DISTINCT s.session_id) AS session_count,
                COUNT(mc.call_id) AS call_count,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_call_count,
                COALESCE(SUM(CASE WHEN mc.status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_call_count,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.prompt_tokens, 0) ELSE 0 END), 0) AS prompt_tokens,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.completion_tokens, 0) ELSE 0 END), 0) AS completion_tokens,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.total_tokens, 0) ELSE 0 END), 0) AS total_tokens,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.duration, 0) ELSE 0 END), 0) AS total_duration,
                MAX(COALESCE(mc.completed_at, mc.created_at)) AS latest_call_at
            FROM sessions s
            LEFT JOIN model_calls mc
                ON mc.session_id = s.session_id
            GROUP BY s.source
            ORDER BY total_tokens DESC, latest_call_at DESC, s.source ASC
            """
        ).fetchall()

        day_rows = conn.execute(
            """
            SELECT
                substr(created_at, 1, 10) AS date,
                COUNT(call_id) AS call_count,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_call_count,
                COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_call_count,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN COALESCE(prompt_tokens, 0) ELSE 0 END), 0) AS prompt_tokens,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN COALESCE(completion_tokens, 0) ELSE 0 END), 0) AS completion_tokens,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN COALESCE(total_tokens, 0) ELSE 0 END), 0) AS total_tokens,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN COALESCE(duration, 0) ELSE 0 END), 0) AS total_duration
            FROM model_calls
            GROUP BY substr(created_at, 1, 10)
            ORDER BY date DESC
            LIMIT ?
            """,
            (int(day_limit),),
        ).fetchall()

        session_rows = conn.execute(
            """
            SELECT
                s.session_id,
                s.source,
                s.entrypoint,
                s.default_model,
                s.provider_route,
                s.base_url,
                COUNT(mc.call_id) AS call_count,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_call_count,
                COALESCE(SUM(CASE WHEN mc.status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_call_count,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.prompt_tokens, 0) ELSE 0 END), 0) AS prompt_tokens,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.completion_tokens, 0) ELSE 0 END), 0) AS completion_tokens,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.total_tokens, 0) ELSE 0 END), 0) AS total_tokens,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.duration, 0) ELSE 0 END), 0) AS total_duration,
                MAX(COALESCE(mc.completed_at, mc.created_at)) AS last_call_at,
                (
                    SELECT mc2.status
                    FROM model_calls mc2
                    WHERE mc2.session_id = s.session_id
                    ORDER BY mc2.created_at DESC, mc2.call_id DESC
                    LIMIT 1
                ) AS last_status,
                s.updated_at
            FROM sessions s
            LEFT JOIN model_calls mc
                ON mc.session_id = s.session_id
            GROUP BY
                s.session_id,
                s.source,
                s.entrypoint,
                s.default_model,
                s.provider_route,
                s.base_url,
                s.updated_at
            ORDER BY
                CASE WHEN last_call_at IS NULL THEN 1 ELSE 0 END,
                last_call_at DESC,
                s.updated_at DESC,
                s.session_id ASC
            LIMIT ?
            """,
            (int(session_limit),),
        ).fetchall()

        recent_call_rows = conn.execute(
            """
            SELECT
                mc.call_id,
                mc.session_id,
                s.source,
                s.entrypoint,
                s.default_model,
                mc.model,
                mc.provider_route,
                mc.reasoning_effort,
                mc.stream,
                mc.status,
                mc.duration,
                mc.prompt_tokens,
                mc.completion_tokens,
                mc.total_tokens,
                mc.error_type,
                mc.error_message,
                mc.created_at,
                mc.completed_at
            FROM model_calls mc
            JOIN sessions s
                ON s.session_id = mc.session_id
            ORDER BY mc.created_at DESC, mc.call_id DESC
            LIMIT ?
            """,
            (int(call_limit),),
        ).fetchall()

    completed_call_count = _as_int(summary_row["completed_call_count"] if summary_row else 0)
    total_tokens = _as_int(summary_row["total_tokens"] if summary_row else 0)
    total_duration = _as_float(summary_row["total_duration"] if summary_row else 0.0)

    return {
        "summary": {
            "session_count": _as_int(summary_row["session_count"] if summary_row else 0),
            "completed_call_count": completed_call_count,
            "failed_call_count": _as_int(summary_row["failed_call_count"] if summary_row else 0),
            "prompt_tokens": _as_int(summary_row["prompt_tokens"] if summary_row else 0),
            "completion_tokens": _as_int(summary_row["completion_tokens"] if summary_row else 0),
            "total_tokens": total_tokens,
            "total_duration": total_duration,
            "average_duration": (total_duration / completed_call_count) if completed_call_count else 0.0,
            "average_tokens_per_call": (total_tokens / completed_call_count) if completed_call_count else 0.0,
            "average_tokens_per_second": (total_tokens / total_duration) if total_duration else 0.0,
            "earliest_call_at": summary_row["earliest_call_at"] if summary_row else None,
            "latest_call_at": summary_row["latest_call_at"] if summary_row else None,
        },
        "by_source": [_build_usage_row(row) for row in source_rows],
        "by_day": [_build_usage_row(row) for row in day_rows],
        "sessions": [_build_usage_row(row) for row in session_rows],
        "recent_calls": [_build_usage_row(row) for row in recent_call_rows],
    }


class SessionRecorder:
    def __init__(
        self,
        *,
        session_id=None,
        source,
        entrypoint,
        history_dir=None,
        context_file=None,
        default_model=None,
        provider_route=None,
        base_url=None,
        cwd=None,
        created_at=None,
    ):
        self.history_dir = Path(history_dir) if history_dir else Config.get_history_dir()
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.db_file = _db_path(self.history_dir)
        _ensure_db(self.db_file)

        self.session_id = session_id or str(uuid.uuid4())
        self.source = source
        self.entrypoint = entrypoint
        self.context_file = str(context_file) if context_file else None
        self.default_model = default_model
        self.provider_route = provider_route
        self.base_url = base_url
        self.cwd = str(cwd or Path.cwd())
        self.created_at = created_at or _now()

        existing_rollout = self._lookup_rollout_path(self.session_id)
        if existing_rollout:
            self.rollout_path = existing_rollout
        else:
            self.rollout_path = self._build_rollout_path()
            self._write_session_meta()

    def _lookup_rollout_path(self, session_id):
        with _open_db(self.db_file) as conn:
            row = conn.execute(
                "SELECT rollout_path FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        return Path(row[0])

    def _build_rollout_path(self):
        dated = _sessions_root(self.history_dir) / self.created_at.strftime("%Y") / self.created_at.strftime("%m") / self.created_at.strftime("%d")
        dated.mkdir(parents=True, exist_ok=True)
        filename = f"session-{_filename_timestamp(self.created_at)}-{_sanitize_filename(self.session_id)}.jsonl"
        return dated / filename

    def _append_event(self, event_type, payload, *, timestamp=None):
        event = {
            "timestamp": _isoformat(timestamp),
            "type": event_type,
            "payload": payload,
        }
        self.rollout_path.parent.mkdir(parents=True, exist_ok=True)
        with self.rollout_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _upsert_session_row(self):
        now_text = _isoformat()
        with _open_db(self.db_file) as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, created_at, updated_at, source, entrypoint, cwd,
                    context_file, default_model, provider_route, base_url, rollout_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    source=excluded.source,
                    entrypoint=excluded.entrypoint,
                    cwd=excluded.cwd,
                    context_file=excluded.context_file,
                    default_model=excluded.default_model,
                    provider_route=excluded.provider_route,
                    base_url=excluded.base_url,
                    rollout_path=excluded.rollout_path
                """,
                (
                    self.session_id,
                    _isoformat(self.created_at),
                    now_text,
                    self.source,
                    self.entrypoint,
                    self.cwd,
                    self.context_file,
                    self.default_model,
                    self.provider_route,
                    self.base_url,
                    str(self.rollout_path),
                ),
            )

    def _write_session_meta(self):
        self._append_event(
            "session_meta",
            {
                "session_id": self.session_id,
                "created_at": _isoformat(self.created_at),
                "source": self.source,
                "entrypoint": self.entrypoint,
                "cwd": self.cwd,
                "context_file": self.context_file,
                "default_model": self.default_model,
                "provider_route": self.provider_route,
                "base_url": self.base_url,
            },
            timestamp=self.created_at,
        )
        self._upsert_session_row()

    def record_request_started(
        self,
        *,
        call_id,
        model,
        provider_route,
        stream,
        reasoning_effort,
        messages=None,
        metadata=None,
    ):
        created_at = _isoformat()
        self._append_event(
            "request_started",
            {
                "call_id": call_id,
                "session_id": self.session_id,
                "model": model,
                "provider_route": provider_route,
                "stream": bool(stream),
                "reasoning_effort": reasoning_effort,
                "message_count": len(messages or []),
                "metadata": metadata or {},
            },
        )
        with _open_db(self.db_file) as conn:
            conn.execute(
                """
                INSERT INTO model_calls (
                    call_id, session_id, created_at, completed_at, status, model,
                    provider_route, reasoning_effort, stream, duration,
                    prompt_tokens, completion_tokens, total_tokens, error_type, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(call_id) DO UPDATE SET
                    session_id=excluded.session_id,
                    model=excluded.model,
                    provider_route=excluded.provider_route,
                    reasoning_effort=excluded.reasoning_effort,
                    stream=excluded.stream,
                    status=excluded.status
                """,
                (
                    call_id,
                    self.session_id,
                    created_at,
                    None,
                    "started",
                    model,
                    provider_route,
                    reasoning_effort,
                    1 if stream else 0,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                ),
            )
        self._upsert_session_row()
        if messages is not None:
            self.record_message_snapshot(call_id=call_id, messages=messages)

    def record_message_snapshot(self, *, call_id, messages):
        normalized = list(messages or [])
        self._append_event(
            "message_snapshot",
            {
                "call_id": call_id,
                "session_id": self.session_id,
                "messages": normalized,
            },
        )
        with _open_db(self.db_file) as conn:
            conn.execute(
                "DELETE FROM session_messages WHERE session_id = ? AND call_id = ?",
                (self.session_id, call_id),
            )
            for index, message in enumerate(normalized):
                conn.execute(
                    """
                    INSERT INTO session_messages (session_id, call_id, message_index, role, content_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        self.session_id,
                        call_id,
                        index,
                        message.get("role", ""),
                        json.dumps(message.get("content"), ensure_ascii=False),
                    ),
                )
        self._upsert_session_row()

    def record_request_completed(
        self,
        *,
        call_id,
        model,
        provider_route,
        stream,
        reasoning_effort,
        content,
        thinking,
        usage,
        duration,
    ):
        normalized_usage = _normalize_usage(usage)
        completed_at = _isoformat()
        self._append_event(
            "request_completed",
            {
                "call_id": call_id,
                "session_id": self.session_id,
                "model": model,
                "provider_route": provider_route,
                "stream": bool(stream),
                "reasoning_effort": reasoning_effort,
                "content": content,
                "thinking": thinking,
                "usage": normalized_usage,
                "duration": duration,
                "status": "completed",
            },
        )
        with _open_db(self.db_file) as conn:
            conn.execute(
                """
                UPDATE model_calls
                SET completed_at = ?, status = ?, model = ?, provider_route = ?,
                    reasoning_effort = ?, stream = ?, duration = ?, prompt_tokens = ?,
                    completion_tokens = ?, total_tokens = ?, error_type = NULL, error_message = NULL
                WHERE call_id = ?
                """,
                (
                    completed_at,
                    "completed",
                    model,
                    provider_route,
                    reasoning_effort,
                    1 if stream else 0,
                    duration,
                    normalized_usage["prompt_tokens"],
                    normalized_usage["completion_tokens"],
                    normalized_usage["total_tokens"],
                    call_id,
                ),
            )
        self._upsert_session_row()

    def record_token_count(self, *, call_id, last_token_usage, total_token_usage=None):
        last_usage = _normalize_usage(last_token_usage)
        total_usage = _normalize_usage(total_token_usage or last_token_usage)
        self._append_event(
            "token_count",
            {
                "call_id": call_id,
                "session_id": self.session_id,
                "last_token_usage": last_usage,
                "total_token_usage": total_usage,
            },
        )
        self._upsert_session_row()

    def record_request_failed(
        self,
        *,
        call_id,
        error,
        model,
        provider_route,
        stream,
        reasoning_effort,
        duration,
    ):
        completed_at = _isoformat()
        error_type = type(error).__name__
        error_message = str(error)
        self._append_event(
            "request_failed",
            {
                "call_id": call_id,
                "session_id": self.session_id,
                "model": model,
                "provider_route": provider_route,
                "stream": bool(stream),
                "reasoning_effort": reasoning_effort,
                "duration": duration,
                "error_type": error_type,
                "error_message": error_message,
                "status": "failed",
            },
        )
        with _open_db(self.db_file) as conn:
            conn.execute(
                """
                UPDATE model_calls
                SET completed_at = ?, status = ?, model = ?, provider_route = ?,
                    reasoning_effort = ?, stream = ?, duration = ?, error_type = ?, error_message = ?
                WHERE call_id = ?
                """,
                (
                    completed_at,
                    "failed",
                    model,
                    provider_route,
                    reasoning_effort,
                    1 if stream else 0,
                    duration,
                    error_type,
                    error_message,
                    call_id,
                ),
            )
        self._upsert_session_row()

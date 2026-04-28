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
                service_tier TEXT,
                stream INTEGER NOT NULL,
                duration REAL,
                first_token_latency REAL,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                total_tokens INTEGER,
                prompt_cache_hit_tokens INTEGER,
                prompt_cache_miss_tokens INTEGER,
                completion_reasoning_tokens INTEGER,
                usage_json TEXT,
                response_json TEXT,
                request_metadata_json TEXT,
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
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(model_calls)").fetchall()
        }
        if "first_token_latency" not in columns:
            conn.execute("ALTER TABLE model_calls ADD COLUMN first_token_latency REAL")
        for column_name, column_type in (
            ("prompt_cache_hit_tokens", "INTEGER"),
            ("prompt_cache_miss_tokens", "INTEGER"),
            ("completion_reasoning_tokens", "INTEGER"),
            ("usage_json", "TEXT"),
            ("response_json", "TEXT"),
            ("request_metadata_json", "TEXT"),
            ("service_tier", "TEXT"),
        ):
            if column_name not in columns:
                conn.execute(f"ALTER TABLE model_calls ADD COLUMN {column_name} {column_type}")


def _json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return _json_safe(value.model_dump())
        except Exception:
            pass
    if hasattr(value, "dict"):
        try:
            return _json_safe(value.dict())
        except Exception:
            pass
    if hasattr(value, "to_dict"):
        try:
            return _json_safe(value.to_dict())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        public_items = {
            key: item
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
        if public_items:
            return _json_safe(public_items)
    return str(value)


def _json_dumps_or_none(value):
    safe_value = _json_safe(value)
    if safe_value is None:
        return None
    return json.dumps(safe_value, ensure_ascii=False, sort_keys=True)


def _json_loads_or_none(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def _as_int_or_zero(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_int_or_none(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nested_value(payload, *keys):
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _without_raw_usage(normalized_usage):
    return {
        key: value
        for key, value in normalized_usage.items()
        if key != "usage_raw"
    }


def _normalize_usage(usage):
    raw_usage = _json_safe(usage) or {}
    if not isinstance(raw_usage, dict):
        raw_usage = {}

    prompt_tokens = _as_int_or_zero(raw_usage.get("prompt_tokens"))
    completion_tokens = _as_int_or_zero(raw_usage.get("completion_tokens"))
    total_tokens = _as_int_or_zero(raw_usage.get("total_tokens"))

    prompt_cache_hit_tokens = _as_int_or_none(raw_usage.get("prompt_cache_hit_tokens"))
    if prompt_cache_hit_tokens is None:
        prompt_cache_hit_tokens = _as_int_or_none(
            _nested_value(raw_usage, "prompt_tokens_details", "cached_tokens")
        )

    prompt_cache_miss_tokens = _as_int_or_none(raw_usage.get("prompt_cache_miss_tokens"))
    if prompt_cache_miss_tokens is None and prompt_cache_hit_tokens is not None:
        prompt_cache_miss_tokens = max(prompt_tokens - prompt_cache_hit_tokens, 0)

    completion_reasoning_tokens = _as_int_or_none(raw_usage.get("completion_reasoning_tokens"))
    if completion_reasoning_tokens is None:
        completion_reasoning_tokens = _as_int_or_none(raw_usage.get("reasoning_tokens"))
    if completion_reasoning_tokens is None:
        completion_reasoning_tokens = _as_int_or_none(
            _nested_value(raw_usage, "completion_tokens_details", "reasoning_tokens")
        )

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "prompt_cache_hit_tokens": prompt_cache_hit_tokens,
        "prompt_cache_miss_tokens": prompt_cache_miss_tokens,
        "completion_reasoning_tokens": completion_reasoning_tokens,
        "usage_raw": raw_usage,
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
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.prompt_cache_hit_tokens, 0) ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.prompt_cache_miss_tokens, 0) ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.completion_reasoning_tokens, 0) ELSE 0 END), 0),
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
        prompt_cache_hit_tokens,
        prompt_cache_miss_tokens,
        completion_reasoning_tokens,
        total_duration,
        call_count,
    ) = row

    average_duration = float(total_duration) / int(call_count) if call_count else 0.0
    cache_denominator = int(prompt_cache_hit_tokens) + int(prompt_cache_miss_tokens)
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
        "prompt_cache_hit_tokens": int(prompt_cache_hit_tokens),
        "prompt_cache_miss_tokens": int(prompt_cache_miss_tokens),
        "prompt_cache_hit_rate": (int(prompt_cache_hit_tokens) / cache_denominator * 100) if cache_denominator else None,
        "completion_reasoning_tokens": int(completion_reasoning_tokens),
        "total_duration": float(total_duration),
        "average_duration": average_duration,
    }


def get_usage_dashboard_snapshot(db_file=None, *, day_limit=14, session_limit=10, call_limit=20, speed_limit=120):
    resolved_db_file = Path(db_file) if db_file else _db_path(Config.get_history_dir())
    _ensure_db(resolved_db_file)

    def _as_int(value):
        return int(value or 0)

    def _as_float(value):
        return float(value or 0.0)

    def _optional_int(payload, key):
        if payload.get(key) is None:
            return None
        return _as_int(payload.get(key))

    def _build_usage_row(row):
        keys = set(row.keys())
        payload = {key: row[key] for key in row.keys()}
        if "request_metadata_json" in keys:
            payload["request_metadata"] = _json_loads_or_none(payload.get("request_metadata_json"))
        completed = _as_int(payload["completed_call_count"]) if "completed_call_count" in keys else (1 if payload.get("status") == "completed" else 0)
        total_duration = _as_float(payload["total_duration"]) if "total_duration" in keys else _as_float(payload.get("duration"))
        total_tokens = _as_int(payload["total_tokens"])
        completion_tokens = _as_int(payload.get("completion_tokens"))
        payload["session_count"] = _as_int(payload.get("session_count"))
        payload["call_count"] = _as_int(payload.get("call_count")) if "call_count" in keys else 1
        payload["completed_call_count"] = completed
        payload["failed_call_count"] = _as_int(payload.get("failed_call_count")) if "failed_call_count" in keys else (1 if payload.get("status") == "failed" else 0)
        payload["prompt_tokens"] = _as_int(payload.get("prompt_tokens"))
        payload["completion_tokens"] = completion_tokens
        payload["total_tokens"] = total_tokens
        cache_recorded_count = _as_int(payload.get("cache_recorded_call_count")) if "cache_recorded_call_count" in keys else None
        reasoning_recorded_count = _as_int(payload.get("reasoning_recorded_call_count")) if "reasoning_recorded_call_count" in keys else None
        if cache_recorded_count is None:
            cache_recorded = (
                payload.get("prompt_cache_hit_tokens") is not None
                or payload.get("prompt_cache_miss_tokens") is not None
            )
        else:
            cache_recorded = cache_recorded_count > 0
            payload["cache_recorded_call_count"] = cache_recorded_count
        if reasoning_recorded_count is None:
            reasoning_recorded = payload.get("completion_reasoning_tokens") is not None
        else:
            reasoning_recorded = reasoning_recorded_count > 0
            payload["reasoning_recorded_call_count"] = reasoning_recorded_count
        payload["prompt_cache_hit_tokens"] = _as_int(payload.get("prompt_cache_hit_tokens")) if cache_recorded else None
        payload["prompt_cache_miss_tokens"] = _as_int(payload.get("prompt_cache_miss_tokens")) if cache_recorded else None
        payload["completion_reasoning_tokens"] = _optional_int(payload, "completion_reasoning_tokens") if reasoning_recorded else None
        cache_hit = _as_int(payload.get("prompt_cache_hit_tokens"))
        cache_miss = _as_int(payload.get("prompt_cache_miss_tokens"))
        cache_total = cache_hit + cache_miss
        payload["prompt_cache_hit_rate"] = (cache_hit / cache_total * 100) if cache_recorded and cache_total else (0.0 if cache_recorded else None)
        payload["total_duration"] = total_duration
        payload["average_duration"] = (total_duration / completed) if completed else 0.0
        payload["average_tokens_per_call"] = (total_tokens / completed) if completed else 0.0
        payload["average_tokens_per_second"] = (total_tokens / total_duration) if total_duration else 0.0
        payload["output_tokens_per_second"] = (completion_tokens / total_duration) if total_duration else 0.0
        if "stream" in payload:
            payload["stream"] = bool(payload["stream"]) if payload["stream"] is not None else None
        for raw_key in ("usage_json", "response_json", "request_metadata_json", "request_metadata"):
            payload.pop(raw_key, None)
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
                COALESCE(SUM(CASE WHEN status = 'completed' THEN COALESCE(prompt_cache_hit_tokens, 0) ELSE 0 END), 0) AS prompt_cache_hit_tokens,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN COALESCE(prompt_cache_miss_tokens, 0) ELSE 0 END), 0) AS prompt_cache_miss_tokens,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN COALESCE(completion_reasoning_tokens, 0) ELSE 0 END), 0) AS completion_reasoning_tokens,
                COALESCE(SUM(CASE WHEN status = 'completed' AND (prompt_cache_hit_tokens IS NOT NULL OR prompt_cache_miss_tokens IS NOT NULL) THEN 1 ELSE 0 END), 0) AS cache_recorded_call_count,
                COALESCE(SUM(CASE WHEN status = 'completed' AND completion_reasoning_tokens IS NOT NULL THEN 1 ELSE 0 END), 0) AS reasoning_recorded_call_count,
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
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.prompt_cache_hit_tokens, 0) ELSE 0 END), 0) AS prompt_cache_hit_tokens,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.prompt_cache_miss_tokens, 0) ELSE 0 END), 0) AS prompt_cache_miss_tokens,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.completion_reasoning_tokens, 0) ELSE 0 END), 0) AS completion_reasoning_tokens,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' AND (mc.prompt_cache_hit_tokens IS NOT NULL OR mc.prompt_cache_miss_tokens IS NOT NULL) THEN 1 ELSE 0 END), 0) AS cache_recorded_call_count,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' AND mc.completion_reasoning_tokens IS NOT NULL THEN 1 ELSE 0 END), 0) AS reasoning_recorded_call_count,
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
                COALESCE(SUM(CASE WHEN status = 'completed' THEN COALESCE(prompt_cache_hit_tokens, 0) ELSE 0 END), 0) AS prompt_cache_hit_tokens,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN COALESCE(prompt_cache_miss_tokens, 0) ELSE 0 END), 0) AS prompt_cache_miss_tokens,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN COALESCE(completion_reasoning_tokens, 0) ELSE 0 END), 0) AS completion_reasoning_tokens,
                COALESCE(SUM(CASE WHEN status = 'completed' AND (prompt_cache_hit_tokens IS NOT NULL OR prompt_cache_miss_tokens IS NOT NULL) THEN 1 ELSE 0 END), 0) AS cache_recorded_call_count,
                COALESCE(SUM(CASE WHEN status = 'completed' AND completion_reasoning_tokens IS NOT NULL THEN 1 ELSE 0 END), 0) AS reasoning_recorded_call_count,
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
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.prompt_cache_hit_tokens, 0) ELSE 0 END), 0) AS prompt_cache_hit_tokens,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.prompt_cache_miss_tokens, 0) ELSE 0 END), 0) AS prompt_cache_miss_tokens,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' THEN COALESCE(mc.completion_reasoning_tokens, 0) ELSE 0 END), 0) AS completion_reasoning_tokens,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' AND (mc.prompt_cache_hit_tokens IS NOT NULL OR mc.prompt_cache_miss_tokens IS NOT NULL) THEN 1 ELSE 0 END), 0) AS cache_recorded_call_count,
                COALESCE(SUM(CASE WHEN mc.status = 'completed' AND mc.completion_reasoning_tokens IS NOT NULL THEN 1 ELSE 0 END), 0) AS reasoning_recorded_call_count,
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
                mc.service_tier,
                mc.stream,
                mc.status,
                mc.duration,
                mc.first_token_latency,
                mc.prompt_tokens,
                mc.completion_tokens,
                mc.total_tokens,
                mc.prompt_cache_hit_tokens,
                mc.prompt_cache_miss_tokens,
                mc.completion_reasoning_tokens,
                mc.usage_json,
                mc.response_json,
                mc.request_metadata_json,
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

        speed_rows = conn.execute(
            """
            SELECT *
            FROM (
                SELECT
                    mc.call_id,
                    mc.session_id,
                    s.source,
                    s.entrypoint,
                    s.default_model,
                    mc.model,
                    mc.provider_route,
                    mc.reasoning_effort,
                    mc.service_tier,
                    mc.stream,
                    mc.status,
                    mc.duration,
                    mc.first_token_latency,
                    mc.prompt_tokens,
                    mc.completion_tokens,
                    mc.total_tokens,
                    mc.prompt_cache_hit_tokens,
                    mc.prompt_cache_miss_tokens,
                    mc.completion_reasoning_tokens,
                    mc.usage_json,
                    mc.created_at,
                    mc.completed_at
                FROM model_calls mc
                JOIN sessions s
                    ON s.session_id = mc.session_id
                WHERE mc.status = 'completed'
                    AND COALESCE(mc.duration, 0) > 0
                    AND COALESCE(mc.total_tokens, 0) > 0
                ORDER BY mc.created_at DESC, mc.call_id DESC
                LIMIT ?
            ) AS recent_speed_calls
            ORDER BY created_at ASC, call_id ASC
            """,
            (int(speed_limit),),
        ).fetchall()

    completed_call_count = _as_int(summary_row["completed_call_count"] if summary_row else 0)
    completion_tokens = _as_int(summary_row["completion_tokens"] if summary_row else 0)
    total_tokens = _as_int(summary_row["total_tokens"] if summary_row else 0)
    total_duration = _as_float(summary_row["total_duration"] if summary_row else 0.0)
    summary_payload = _build_usage_row(summary_row) if summary_row else {
        "session_count": 0,
        "completed_call_count": 0,
        "failed_call_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "prompt_cache_hit_tokens": None,
        "prompt_cache_miss_tokens": None,
        "completion_reasoning_tokens": None,
        "prompt_cache_hit_rate": None,
        "total_duration": 0.0,
    }

    return {
        "summary": {
            "session_count": _as_int(summary_row["session_count"] if summary_row else 0),
            "completed_call_count": completed_call_count,
            "failed_call_count": _as_int(summary_row["failed_call_count"] if summary_row else 0),
            "prompt_tokens": _as_int(summary_row["prompt_tokens"] if summary_row else 0),
            "completion_tokens": _as_int(summary_row["completion_tokens"] if summary_row else 0),
            "total_tokens": total_tokens,
            "prompt_cache_hit_tokens": summary_payload["prompt_cache_hit_tokens"],
            "prompt_cache_miss_tokens": summary_payload["prompt_cache_miss_tokens"],
            "prompt_cache_hit_rate": summary_payload["prompt_cache_hit_rate"],
            "completion_reasoning_tokens": summary_payload["completion_reasoning_tokens"],
            "total_duration": total_duration,
            "average_duration": (total_duration / completed_call_count) if completed_call_count else 0.0,
            "average_tokens_per_call": (total_tokens / completed_call_count) if completed_call_count else 0.0,
            "average_tokens_per_second": (total_tokens / total_duration) if total_duration else 0.0,
            "output_tokens_per_second": (completion_tokens / total_duration) if total_duration else 0.0,
            "earliest_call_at": summary_row["earliest_call_at"] if summary_row else None,
            "latest_call_at": summary_row["latest_call_at"] if summary_row else None,
        },
        "by_source": [_build_usage_row(row) for row in source_rows],
        "by_day": [_build_usage_row(row) for row in day_rows],
        "sessions": [_build_usage_row(row) for row in session_rows],
        "recent_calls": [_build_usage_row(row) for row in recent_call_rows],
        "speed_series": [_build_usage_row(row) for row in speed_rows],
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
        service_tier=None,
        messages=None,
        metadata=None,
    ):
        created_at = _isoformat()
        safe_metadata = _json_safe(metadata or {})
        self._append_event(
            "request_started",
            {
                "call_id": call_id,
                "session_id": self.session_id,
                "model": model,
                "provider_route": provider_route,
                "stream": bool(stream),
                "reasoning_effort": reasoning_effort,
                "service_tier": service_tier,
                "message_count": len(messages or []),
                "metadata": safe_metadata,
            },
        )
        with _open_db(self.db_file) as conn:
            conn.execute(
                """
                INSERT INTO model_calls (
                    call_id, session_id, created_at, completed_at, status, model,
                    provider_route, reasoning_effort, service_tier, stream, duration, first_token_latency,
                    prompt_tokens, completion_tokens, total_tokens, request_metadata_json,
                    error_type, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(call_id) DO UPDATE SET
                    session_id=excluded.session_id,
                    model=excluded.model,
                    provider_route=excluded.provider_route,
                    reasoning_effort=excluded.reasoning_effort,
                    service_tier=excluded.service_tier,
                    stream=excluded.stream,
                    status=excluded.status,
                    first_token_latency=NULL,
                    prompt_cache_hit_tokens=NULL,
                    prompt_cache_miss_tokens=NULL,
                    completion_reasoning_tokens=NULL,
                    usage_json=NULL,
                    response_json=NULL,
                    request_metadata_json=excluded.request_metadata_json
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
                    service_tier,
                    1 if stream else 0,
                    None,
                    None,
                    None,
                    None,
                    None,
                    _json_dumps_or_none(safe_metadata),
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

    def record_response_chunk(self, *, call_id, chunk):
        self._append_event(
            "response_chunk",
            {
                "call_id": call_id,
                "session_id": self.session_id,
                "chunk": _json_safe(chunk),
            },
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
        service_tier=None,
        content,
        thinking,
        usage,
        duration,
        first_token_latency=None,
        response=None,
    ):
        normalized_usage = _normalize_usage(usage)
        usage_payload = _without_raw_usage(normalized_usage)
        usage_raw = normalized_usage["usage_raw"]
        response_raw = _json_safe(response)
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
                "service_tier": service_tier,
                "content": content,
                "thinking": thinking,
                "usage": usage_payload,
                "usage_raw": usage_raw,
                "response_raw": response_raw,
                "duration": duration,
                "first_token_latency": first_token_latency,
                "status": "completed",
            },
        )
        with _open_db(self.db_file) as conn:
            conn.execute(
                """
                UPDATE model_calls
                SET completed_at = ?, status = ?, model = ?, provider_route = ?,
                    reasoning_effort = ?, service_tier = ?, stream = ?, duration = ?, first_token_latency = ?,
                    prompt_tokens = ?, completion_tokens = ?, total_tokens = ?,
                    prompt_cache_hit_tokens = ?, prompt_cache_miss_tokens = ?,
                    completion_reasoning_tokens = ?, usage_json = ?, response_json = ?,
                    error_type = NULL, error_message = NULL
                WHERE call_id = ?
                """,
                (
                    completed_at,
                    "completed",
                    model,
                    provider_route,
                    reasoning_effort,
                    service_tier,
                    1 if stream else 0,
                    duration,
                    first_token_latency,
                    normalized_usage["prompt_tokens"],
                    normalized_usage["completion_tokens"],
                    normalized_usage["total_tokens"],
                    normalized_usage["prompt_cache_hit_tokens"],
                    normalized_usage["prompt_cache_miss_tokens"],
                    normalized_usage["completion_reasoning_tokens"],
                    _json_dumps_or_none(usage_raw),
                    _json_dumps_or_none(response_raw),
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
                "last_token_usage": _without_raw_usage(last_usage),
                "last_token_usage_raw": last_usage["usage_raw"],
                "total_token_usage": _without_raw_usage(total_usage),
                "total_token_usage_raw": total_usage["usage_raw"],
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
        service_tier=None,
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
                "service_tier": service_tier,
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
                    reasoning_effort = ?, service_tier = ?, stream = ?, duration = ?, error_type = ?, error_message = ?
                WHERE call_id = ?
                """,
                (
                    completed_at,
                    "failed",
                    model,
                    provider_route,
                    reasoning_effort,
                    service_tier,
                    1 if stream else 0,
                    duration,
                    error_type,
                    error_message,
                    call_id,
                ),
            )
        self._upsert_session_row()

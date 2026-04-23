import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from src.core.config import Config

FACE_ANALYSIS_DB_FILE = None
REPORT_CACHE_KEY = "latest"
PROGRESS_CACHE_KEY = "latest"
CURRENT_ALGORITHM_VERSION = "dark_circle_v3"
MIGRATABLE_ALGORITHM_VERSIONS = {"dark_circle_v2"}


def get_face_analysis_db_file():
    if FACE_ANALYSIS_DB_FILE:
        return Path(FACE_ANALYSIS_DB_FILE)
    return Path(Config.get_history_dir()) / "face_analysis.db"


def _db_path(db_file=None):
    if db_file is None:
        return get_face_analysis_db_file()
    return Path(db_file)


def _connect(db_file=None):
    path = _db_path(db_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _open_db(db_file=None):
    conn = _connect(db_file)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_face_analysis_db(db_file=None):
    with _open_db(db_file) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS face_analysis_results (
                path TEXT PRIMARY KEY,
                datetime TEXT NOT NULL,
                timestamp REAL NOT NULL,
                passed INTEGER NOT NULL,
                score REAL,
                score_left REAL,
                score_right REAL,
                delta_e_left REAL,
                delta_e_right REAL,
                delta_l_left REAL,
                delta_l_right REAL,
                fail_reason_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS face_report_cache (
                cache_key TEXT PRIMARY KEY,
                report_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS face_progress_cache (
                cache_key TEXT PRIMARY KEY,
                progress_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS face_analysis_meta (
                meta_key TEXT PRIMARY KEY,
                meta_value TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_face_analysis_timestamp
            ON face_analysis_results (timestamp);

            CREATE INDEX IF NOT EXISTS idx_face_analysis_passed
            ON face_analysis_results (passed, timestamp);
            """
        )
    return _db_path(db_file)


def _normalize_float(value):
    if value is None or value == "":
        return None
    return float(value)


def _normalize_bool(value):
    if isinstance(value, bool):
        return value
    if value in (1, "1", "True", "true"):
        return True
    return False


def _normalize_fail_reason(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _get_meta(conn, meta_key):
    row = conn.execute(
        "SELECT meta_value FROM face_analysis_meta WHERE meta_key = ?",
        (meta_key,),
    ).fetchone()
    if not row:
        return None
    return row["meta_value"]


def _set_meta(conn, meta_key, meta_value):
    conn.execute(
        """
        INSERT INTO face_analysis_meta (meta_key, meta_value)
        VALUES (?, ?)
        ON CONFLICT(meta_key) DO UPDATE SET meta_value=excluded.meta_value
        """,
        (meta_key, meta_value),
    )


def _migrate_scores_to_current_algorithm(conn):
    conn.execute(
        """
        UPDATE face_analysis_results
        SET score = CASE
                WHEN passed = 1 AND score IS NOT NULL THEN MIN(100.0, MAX(0.0, score * 10.0))
                ELSE score
            END,
            score_left = CASE
                WHEN passed = 1 AND score_left IS NOT NULL THEN MIN(100.0, MAX(0.0, score_left * 10.0))
                ELSE score_left
            END,
            score_right = CASE
                WHEN passed = 1 AND score_right IS NOT NULL THEN MIN(100.0, MAX(0.0, score_right * 10.0))
                ELSE score_right
            END,
            updated_at = ?
        """,
        (time.time(),),
    )
    conn.execute("DELETE FROM face_report_cache")
    conn.execute("DELETE FROM face_progress_cache")


def initialize_face_analysis_storage(db_file=None, algorithm_version=CURRENT_ALGORITHM_VERSION):
    ensure_face_analysis_db(db_file)
    with _open_db(db_file) as conn:
        existing_version = _get_meta(conn, "analysis_algorithm_version")
        if existing_version != algorithm_version and existing_version in MIGRATABLE_ALGORITHM_VERSIONS:
            _migrate_scores_to_current_algorithm(conn)
        elif existing_version != algorithm_version:
            conn.execute("DELETE FROM face_analysis_results")
            conn.execute("DELETE FROM face_report_cache")
            conn.execute("DELETE FROM face_progress_cache")
        _set_meta(conn, "analysis_algorithm_version", algorithm_version)
        _set_meta(conn, "storage_backend", "sqlite")
    return _db_path(db_file)


def _serialize_record(record):
    return {
        "path": record.get("path", ""),
        "datetime": record.get("datetime", ""),
        "timestamp": float(record.get("timestamp", 0.0) or 0.0),
        "passed": 1 if _normalize_bool(record.get("passed")) else 0,
        "score": _normalize_float(record.get("score")),
        "score_left": _normalize_float(record.get("score_left")),
        "score_right": _normalize_float(record.get("score_right")),
        "delta_e_left": _normalize_float(record.get("delta_e_left")),
        "delta_e_right": _normalize_float(record.get("delta_e_right")),
        "delta_l_left": _normalize_float(record.get("delta_l_left")),
        "delta_l_right": _normalize_float(record.get("delta_l_right")),
        "fail_reason_json": json.dumps(_normalize_fail_reason(record.get("fail_reason")), ensure_ascii=False),
    }


def _deserialize_record(row):
    return {
        "path": row["path"],
        "datetime": row["datetime"],
        "timestamp": row["timestamp"],
        "passed": bool(row["passed"]),
        "score": row["score"],
        "score_left": row["score_left"],
        "score_right": row["score_right"],
        "delta_e_left": row["delta_e_left"],
        "delta_e_right": row["delta_e_right"],
        "delta_l_left": row["delta_l_left"],
        "delta_l_right": row["delta_l_right"],
        "fail_reason": _normalize_fail_reason(row["fail_reason_json"]),
    }


def upsert_face_analysis_record(record, db_file=None):
    ensure_face_analysis_db(db_file)
    payload = _serialize_record(record)
    now = time.time()
    with _open_db(db_file) as conn:
        conn.execute(
            """
            INSERT INTO face_analysis_results (
                path, datetime, timestamp, passed, score, score_left, score_right,
                delta_e_left, delta_e_right, delta_l_left, delta_l_right,
                fail_reason_json, created_at, updated_at
            ) VALUES (
                :path, :datetime, :timestamp, :passed, :score, :score_left, :score_right,
                :delta_e_left, :delta_e_right, :delta_l_left, :delta_l_right,
                :fail_reason_json, :created_at, :updated_at
            )
            ON CONFLICT(path) DO UPDATE SET
                datetime=excluded.datetime,
                timestamp=excluded.timestamp,
                passed=excluded.passed,
                score=excluded.score,
                score_left=excluded.score_left,
                score_right=excluded.score_right,
                delta_e_left=excluded.delta_e_left,
                delta_e_right=excluded.delta_e_right,
                delta_l_left=excluded.delta_l_left,
                delta_l_right=excluded.delta_l_right,
                fail_reason_json=excluded.fail_reason_json,
                updated_at=excluded.updated_at
            """,
            {
                **payload,
                "created_at": now,
                "updated_at": now,
            },
        )


def upsert_face_analysis_records(records, db_file=None):
    for record in records:
        upsert_face_analysis_record(record, db_file=db_file)


def load_face_analysis_records(db_file=None):
    ensure_face_analysis_db(db_file)
    with _open_db(db_file) as conn:
        rows = conn.execute(
            """
            SELECT path, datetime, timestamp, passed, score, score_left, score_right,
                   delta_e_left, delta_e_right, delta_l_left, delta_l_right, fail_reason_json
            FROM face_analysis_results
            ORDER BY timestamp
            """
        ).fetchall()
    return [_deserialize_record(row) for row in rows]


def load_face_analysis_paths(db_file=None):
    ensure_face_analysis_db(db_file)
    with _open_db(db_file) as conn:
        rows = conn.execute("SELECT path FROM face_analysis_results").fetchall()
    return {row["path"] for row in rows}


def clear_face_analysis_records(db_file=None):
    ensure_face_analysis_db(db_file)
    with _open_db(db_file) as conn:
        conn.execute("DELETE FROM face_analysis_results")


def save_face_report_cache(report, db_file=None):
    ensure_face_analysis_db(db_file)
    payload = json.dumps(report, ensure_ascii=False)
    now = time.time()
    with _open_db(db_file) as conn:
        conn.execute(
            """
            INSERT INTO face_report_cache (cache_key, report_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                report_json=excluded.report_json,
                updated_at=excluded.updated_at
            """,
            (REPORT_CACHE_KEY, payload, now),
        )
    return _db_path(db_file)


def clear_face_report_cache(db_file=None):
    ensure_face_analysis_db(db_file)
    with _open_db(db_file) as conn:
        conn.execute("DELETE FROM face_report_cache WHERE cache_key = ?", (REPORT_CACHE_KEY,))


def load_face_report_cache(db_file=None):
    ensure_face_analysis_db(db_file)
    with _open_db(db_file) as conn:
        row = conn.execute(
            "SELECT report_json FROM face_report_cache WHERE cache_key = ?",
            (REPORT_CACHE_KEY,),
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["report_json"])
    except json.JSONDecodeError:
        return None


def save_face_progress_cache(progress, db_file=None):
    ensure_face_analysis_db(db_file)
    payload = json.dumps(progress, ensure_ascii=False)
    now = time.time()
    with _open_db(db_file) as conn:
        conn.execute(
            """
            INSERT INTO face_progress_cache (cache_key, progress_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                progress_json=excluded.progress_json,
                updated_at=excluded.updated_at
            """,
            (PROGRESS_CACHE_KEY, payload, now),
        )
    return _db_path(db_file)


def clear_face_progress_cache(db_file=None):
    ensure_face_analysis_db(db_file)
    with _open_db(db_file) as conn:
        conn.execute("DELETE FROM face_progress_cache WHERE cache_key = ?", (PROGRESS_CACHE_KEY,))


def load_face_progress_cache(db_file=None):
    ensure_face_analysis_db(db_file)
    with _open_db(db_file) as conn:
        row = conn.execute(
            "SELECT progress_json FROM face_progress_cache WHERE cache_key = ?",
            (PROGRESS_CACHE_KEY,),
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["progress_json"])
    except json.JSONDecodeError:
        return None

"""Synthetic photo, database, and calendar boundary regressions; no real models."""

import sqlite3
import asyncio
import io
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo
from pathlib import Path

import cv2
import numpy as np
import pytest
import httpx
from fastapi import FastAPI

from src.scripts import analyze_face
from src.services import face_analysis_pipeline as pipeline
from src.utils import face_analysis_db as db
from src.manager.take_photo import take_a_photo as photos


def seed(db_file):
    db.initialize_face_analysis_storage(db_file)
    db.upsert_face_analysis_record({
        "path": "synthetic.jpg", "datetime": "2026-04-01 12:00:00", "timestamp": 1775044800,
        "passed": True, "score": 1.2, "score_left": 1.0, "score_right": 1.4,
    }, db_file)


def test_concurrent_old_database_migration_only_scales_scores_once(tmp_path, monkeypatch):
    target = tmp_path / "face.db"
    seed(target)
    with sqlite3.connect(target) as connection:
        connection.execute("UPDATE face_analysis_meta SET meta_value='dark_circle_v2' WHERE meta_key='analysis_algorithm_version'")
    first_read = threading.Event()
    second_read = threading.Event()
    release = threading.Event()
    real_get = db._get_meta
    count = [0]

    def gated_get(connection, key):
        value = real_get(connection, key)
        if key == "analysis_algorithm_version" and value == "dark_circle_v2":
            count[0] += 1
            (first_read if count[0] == 1 else second_read).set()
            assert release.wait(3)
        return value

    monkeypatch.setattr(db, "_get_meta", gated_get)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(db.initialize_face_analysis_storage, target)
        assert first_read.wait(3)
        second = pool.submit(db.initialize_face_analysis_storage, target)
        second_read.wait(0.15)  # Correct locking prevents a second old-version read.
        release.set()
        first.result(timeout=3)
        second.result(timeout=3)
    row = db.load_face_analysis_records(target)[0]
    assert (row["score"], row["score_left"], row["score_right"]) == (12, 10, 14)


def test_failed_migration_rolls_back_scores_and_version_then_retries_once(tmp_path, monkeypatch):
    target = tmp_path / "face.db"
    seed(target)
    with sqlite3.connect(target) as connection:
        connection.execute("UPDATE face_analysis_meta SET meta_value='dark_circle_v2' WHERE meta_key='analysis_algorithm_version'")
    real_migrate = db._migrate_scores_to_current_algorithm

    def interrupted(connection):
        real_migrate(connection)
        raise OSError("synthetic interruption")

    with monkeypatch.context() as context:
        context.setattr(db, "_migrate_scores_to_current_algorithm", interrupted)
        with pytest.raises(OSError, match="synthetic interruption"):
            db.initialize_face_analysis_storage(target)
    assert db.load_face_analysis_records(target)[0]["score"] == 1.2
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT meta_value FROM face_analysis_meta WHERE meta_key='analysis_algorithm_version'").fetchone()[0] == "dark_circle_v2"
    db.initialize_face_analysis_storage(target)
    db.initialize_face_analysis_storage(target)
    assert db.load_face_analysis_records(target)[0]["score"] == 12


@pytest.mark.parametrize("content", [b"", b"not a JPEG"])
def test_one_unreadable_photo_does_not_abort_later_photos(tmp_path, monkeypatch, content):
    root = tmp_path / "photos"
    root.mkdir()
    (root / "photo_20260401_080000.jpg").write_bytes(content)
    cv2.imwrite(str(root / "photo_20260401_080100.jpg"), np.zeros((8, 8, 3), np.uint8))
    target = tmp_path / "face.db"
    monkeypatch.setattr(analyze_face, "DB_FILE", target)
    monkeypatch.setattr(analyze_face, "MediaPipeFaceDetector", lambda **_: SimpleNamespace(detect=lambda _: None))
    monkeypatch.setattr(analyze_face, "FaceParser", lambda _: None)
    records, _ = analyze_face.run_analysis([root], "unused.onnx", target, tmp_path / "plots")
    assert len(records) == 2
    assert records[0]["fail_reason"] == ["ReadError"]
    assert records[1]["fail_reason"] == ["NoFace"]
    assert db.load_face_progress_cache(target)["status"] == "done"


@pytest.mark.parametrize("zone", ["UTC", "Asia/Shanghai", "America/Los_Angeles"])
def test_daily_aggregate_timestamp_represents_the_declared_local_date(zone):
    local_zone = ZoneInfo(zone)

    class LocalClock(datetime):
        @classmethod
        def fromisoformat(cls, text):
            value = datetime.fromisoformat(text)
            return value.replace(tzinfo=local_zone) if value.tzinfo is None else value

    records = [{"datetime": f"2026-11-{day:02d} 12:00:00", "timestamp": datetime(2026, 11, day, 12, tzinfo=local_zone).timestamp(), "score": 20} for day in (1, 3)]
    with patch.object(pipeline, "datetime", LocalClock):
        views = pipeline.build_trend_views(records)
    for key in ["week", "month", "all"]:
        for point in views[key]["points"]:
            assert datetime.fromtimestamp(point["timestamp"], local_zone).strftime("%Y-%m-%d %H:%M:%S") == point["datetime"]
    node = shutil.which("node")
    if node:
        import json
        script = "import {buildChartModel} from './src/webapp/src/components/faceTrendChart.js'; const m=buildChartModel({points:JSON.parse(process.argv[1]),width:600,height:300}); console.log(JSON.stringify(m.ticks.map(t=>t.label)));"
        output = subprocess.run([node, "--input-type=module", "-e", script, json.dumps(views["all"]["points"])],
                                cwd=Path(__file__).resolve().parents[1], env={**os.environ, "TZ": zone},
                                capture_output=True, text=True, check=True)
        assert "11-01" in output.stdout


def test_dst_repeated_hour_keeps_distinct_captures_and_same_minute_dedup(tmp_path, monkeypatch):
    frame = np.zeros((4, 4, 3), np.uint8)
    zone = ZoneInfo("America/Los_Angeles")
    first = datetime(2026, 11, 1, 1, 30, 5, tzinfo=zone, fold=0)
    second = first.replace(fold=1)
    saved = []

    def save(path, *_):
        saved.append(path)
        Path(path).write_bytes(b"synthetic image")

    monkeypatch.setattr(photos, "save_image_with_gps", save)
    gate = photos.PresencePhotoMinuteGate()
    one = gate.save(frame, tmp_path, captured_at=first)
    assert gate.save(frame, tmp_path, captured_at=first.replace(second=25)) == one
    two = gate.save(frame, tmp_path, captured_at=second)
    assert one != two
    assert len(saved) == 2
    found = pipeline.scan_photos([tmp_path])
    assert len(found) == 2
    assert found[1]["timestamp"] - found[0]["timestamp"] == 3600
    restarted = photos.PresencePhotoMinuteGate()
    assert restarted.save(frame, tmp_path, captured_at=first) == one
    assert restarted.save(frame, tmp_path, captured_at=second) == two
    assert len(list(tmp_path.rglob("*.jpg"))) == 2


def test_concurrent_face_exports_use_independent_complete_workbooks(tmp_path, monkeypatch):
    target = tmp_path / "face.db"
    seed(target)
    monkeypatch.setattr(analyze_face.Config, "get_runtime_dir", lambda: tmp_path / "runtime")
    with ThreadPoolExecutor(max_workers=2) as pool:
        paths = list(pool.map(lambda _: analyze_face.export_excel(target), range(2)))
    assert len(set(paths)) == 2
    import zipfile
    for path in paths:
        with zipfile.ZipFile(path) as workbook:
            assert workbook.testzip() is None


def test_real_http_exports_run_isolated_subprocesses_and_cleanup_after_download(tmp_path, monkeypatch):
    from src.backend import face
    import zipfile
    for name in ("DATA", "CONFIG", "HISTORY", "RUNTIME", "CACHE", "LOG", "PLOT", "MIGRATION"):
        monkeypatch.setenv(f"VANTAGE_{name}_DIR", str(tmp_path / name.lower()))
    target = face.profile_paths()["db_file"]
    seed(target)
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(face._processes, "_build_face_analysis_subprocess", lambda args=None: (
        [sys.executable, str(root / "src/scripts/analyze_face.py"), *(args or [])], str(root),
    ))
    app = FastAPI()
    app.include_router(face.router)

    async def download():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", timeout=30) as client:
            return await asyncio.gather(*(client.get("/api/v1/face/export") for _ in range(3)))

    responses = asyncio.run(download())
    for response in responses:
        assert response.status_code == 200, response.text
        assert 'Face_Analysis_History.xlsx' in response.headers['content-disposition']
        with zipfile.ZipFile(io.BytesIO(response.content)) as workbook:
            assert workbook.testzip() is None
    assert not list((tmp_path / "runtime" / "exports").glob("*.xlsx"))

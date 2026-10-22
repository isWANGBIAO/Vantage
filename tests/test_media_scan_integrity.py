"""Synthetic filesystem regressions for latest-media and partial storage scans."""

import asyncio
import os
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend import media, runtime, system
from src.services.directory_size_scanner import DirectorySizeScanner


@pytest.mark.parametrize("extension", ["jpg", "png"])
def test_latest_scan_traverses_older_ancestors_containing_newer_files(tmp_path, extension, monkeypatch):
    current = tmp_path / "2026" / "10" / "12" / "10"
    current.mkdir(parents=True)
    time.sleep(0.03)
    restored = tmp_path / "2026" / "10" / "11" / "10"
    restored.mkdir(parents=True)
    old = restored / f"old.{extension}"
    old.write_bytes(b"old metadata fixture")
    time.sleep(0.03)
    latest = current / f"latest.{extension}"
    latest.write_bytes(b"new metadata fixture")

    assert latest.stat().st_mtime > old.stat().st_mtime
    found = media.find_latest_file_recursive(tmp_path, max_entries=None, max_seconds=None)
    assert found == str(latest)
    assert media.find_latest_file_recursive.last_truncated is False
    state = runtime.SystemState()
    monkeypatch.setattr(runtime, "state", state)
    state.photos_path = str(tmp_path)
    monkeypatch.setattr(media, "_saved_photo_contains_person", lambda _: True)
    media.initialize_latest_media_state()
    app = FastAPI()
    app.include_router(media.router)
    with TestClient(app) as http:
        response = http.get("/api/v1/media/latest")
    assert response.status_code == 200
    assert response.json()["photo_name"] == latest.name
    assert response.json()["latest_media_scan_truncated"] is False


def test_latest_scan_reports_unreadable_subtree_as_partial(tmp_path, monkeypatch):
    denied = tmp_path / "denied"
    denied.mkdir()
    known = tmp_path / "known.jpg"
    known.write_bytes(b"metadata fixture")
    scandir = os.scandir

    def checked(path):
        if Path(path) == denied:
            raise PermissionError("synthetic unreadable subtree")
        return scandir(path)

    monkeypatch.setattr(media.os, "scandir", checked)
    assert media.find_latest_file_recursive(tmp_path, max_entries=None, max_seconds=None) == str(known)
    assert media.find_latest_file_recursive.last_truncated is True


def test_storage_partial_flag_reaches_public_statistics_and_clears_after_refresh(tmp_path, monkeypatch):
    (tmp_path / "known.bin").write_bytes(b"a" * 1024**2)
    denied = tmp_path / "denied"
    denied.mkdir()
    (denied / "hidden.bin").write_bytes(b"b" * (3 * 1024**2))
    state = runtime.SystemState()
    monkeypatch.setattr(runtime, "state", state)
    state.photos_path = str(tmp_path)
    scandir = os.scandir
    readable = [False]

    def checked(path):
        if Path(path) == denied and not readable[0]:
            raise PermissionError("synthetic unreadable subtree")
        return scandir(path)

    def factory(path, **kwargs):
        return DirectorySizeScanner(path, scandir_fn=checked, **kwargs)

    snapshots = []

    def after_iteration(_):
        snapshots.append(asyncio.run(system.get_sys_stats()))
        readable[0] = True
        if len(snapshots) == 2:
            state.is_running = False

    media.update_storage_stats(
        max_entries_per_step=None, max_seconds_per_step=None,
        refresh_interval_seconds=0, scanner_factory=factory, sleep_fn=after_iteration,
    )
    assert snapshots[0]["storage_used_mb"] == 1.0
    assert snapshots[0]["storage_scan_truncated"] is True
    assert snapshots[1]["storage_used_mb"] == 4.0
    assert snapshots[1]["storage_scan_truncated"] is False

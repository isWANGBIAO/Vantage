import asyncio
import json
import os
import re
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.services.body_analysis_jobs import BodyAnalysisJobService, source_snapshot
from src.scripts.body_analysis_sam3 import build_report, validate_report_manifest


def _configured(tmp_path):
    leg, scalp, model = (tmp_path / name for name in ("leg", "scalp", "model"))
    for directory in (leg, scalp, model):
        directory.mkdir()
    (leg / "a.jpg").write_bytes(b"photo")
    (model / "config.json").write_bytes(b"model")
    return {"body_analysis_enabled": True, "body_analysis_leg_dir": str(leg),
            "body_analysis_scalp_dir": str(scalp), "body_analysis_model_dir": str(model)}


def test_snapshot_changes_only_for_supported_images_and_model(tmp_path):
    settings = _configured(tmp_path)
    paths = {key: Path(settings[f"body_analysis_{key}_dir"]) for key in ("leg", "scalp", "model")}
    runner = tmp_path / "runner.py"
    runner.write_text("one")
    first = source_snapshot(paths, runner)
    assert first.counts == {"leg": 1, "scalp": 0}
    (paths["leg"] / "ignored.txt").write_text("new")
    assert source_snapshot(paths, runner).fingerprint == first.fingerprint
    (paths["scalp"] / "new.png").write_bytes(b"new")
    assert source_snapshot(paths, runner).fingerprint != first.fingerprint


def test_snapshot_distinguishes_different_roots_with_identical_file_metadata(tmp_path):
    settings = _configured(tmp_path)
    paths = {key: Path(settings[f"body_analysis_{key}_dir"]) for key in ("leg", "scalp", "model")}
    runner = tmp_path / "runner.py"
    runner.write_text("runner")
    before = source_snapshot(paths, runner)
    alternate_leg = tmp_path / "leg-alternate"
    alternate_leg.mkdir()
    shutil.copy2(paths["leg"] / "a.jpg", alternate_leg / "a.jpg")
    assert (alternate_leg / "a.jpg").stat().st_mtime_ns == (paths["leg"] / "a.jpg").stat().st_mtime_ns
    paths["leg"] = alternate_leg
    after = source_snapshot(paths, runner)
    assert after.counts == before.counts
    assert after.fingerprint != before.fingerprint


def test_start_is_nonblocking_singleflight_and_missing_environment(tmp_path):
    asyncio.run(_check_singleflight(tmp_path))


async def _check_singleflight(tmp_path):
    settings = _configured(tmp_path)
    release = asyncio.Event()

    async def slow_probe(_model):
        await release.wait()
        return {"state": "missing_dependencies", "ready": False, "missing": ["dependencies"], "reason": "missing_dependencies"}

    service = BodyAnalysisJobService(root=tmp_path / "reports", settings_loader=lambda: settings,
                                     environment_probe=slow_probe, runner_path=tmp_path / "runner.py")
    (tmp_path / "runner.py").write_text("runner")
    service.start()
    first_task = service.active_task
    service.start()
    assert service.active_task is first_task
    assert first_task and not first_task.done()
    release.set()
    await first_task
    assert service.status()["status"] == "missing_environment"
    await service.close()


def test_failure_preserves_old_report_and_successful_fingerprint(tmp_path):
    asyncio.run(_check_failure_preserves_report(tmp_path))


async def _check_failure_preserves_report(tmp_path):
    settings = _configured(tmp_path)
    runner = tmp_path / "runner.py"
    runner.write_text("runner")
    root = tmp_path / "reports"
    service = BodyAnalysisJobService(root=root, settings_loader=lambda: settings,
                                     environment_probe=lambda _: {"state": "ready", "ready": True, "missing": [], "reason": "ready", "python_executable": "python"},
                                     runner_path=runner)
    previous = root / "published" / "old"
    previous.mkdir(parents=True)
    report = {"schema_version": 1, "complete": True, "engine": "sam3", "input_counts": {"leg": 0, "scalp": 0}, "leg": {"records": [], "trend": [], "trend_unavailable_reason": "no_images"}, "scalp": {"records": [], "trend": [], "trend_unavailable_reason": "no_images"}, "assets": []}
    (previous / "report.json").write_text(json.dumps(report))
    assert validate_report_manifest(report, previous)
    root.mkdir(exist_ok=True)
    previous_fingerprint = "a" * 64
    (root / "current.json").write_text(json.dumps({"directory": "old", "fingerprint": previous_fingerprint}))
    assert service._current() is not None
    service.start()
    await service.active_task
    assert service.status()["status"] == "failed"
    assert service.status()["last_report_available"] is True
    assert json.loads((root / "current.json").read_text())["fingerprint"] == previous_fingerprint
    await service.close()


def test_success_publishes_atomically_reuses_and_changed_image_requires_new_report(tmp_path, monkeypatch):
    asyncio.run(_check_publication(tmp_path, monkeypatch))


async def _check_publication(tmp_path, monkeypatch):
    settings = _configured(tmp_path)
    Path(settings["body_analysis_leg_dir"], "a.jpg").unlink()
    runner = tmp_path / "runner.py"
    runner.write_text("runner")
    root = tmp_path / "reports"
    launches = []

    async def fake_exec(*argv, **kwargs):
        launches.append(argv)
        output = Path(argv[argv.index("--output-dir") + 1])
        output.mkdir()
        (output / "report.json").write_text(json.dumps(build_report([], [])))

        async def wait():
            return 0

        return SimpleNamespace(wait=wait, returncode=0)

    monkeypatch.setattr("src.services.body_analysis_jobs.asyncio.create_subprocess_exec", fake_exec)
    service = BodyAnalysisJobService(root=root, settings_loader=lambda: settings,
                                     environment_probe=lambda _: {"ready": True, "missing": [], "reason": "ready", "python_executable": "python"},
                                     runner_path=runner)
    service.start()
    await service.active_task
    assert service.status()["status"] == "ready"
    pointer = json.loads((root / "current.json").read_text())
    assert (root / "published" / pointer["directory"] / "report.json").is_file()
    service.start()
    await service.active_task
    assert len(launches) == 1
    service.environment_probe = lambda _: {"ready": False, "missing": ["dependencies"], "reason": "missing_dependencies"}
    service.start()
    await service.active_task
    assert service.status()["status"] == "missing_environment"
    assert service.status()["last_report_available"] is True
    assert len(launches) == 1
    service.environment_probe = lambda _: {"ready": True, "missing": [], "reason": "ready", "python_executable": "python"}
    Path(settings["body_analysis_leg_dir"], "new.png").write_bytes(b"new")
    service.start()
    await service.active_task
    assert len(launches) == 2
    assert service.status()["status"] == "failed"  # runner reported zero for one photo
    assert json.loads((root / "current.json").read_text()) == pointer
    await service.close()


def test_settings_notification_from_worker_thread_starts_scan_without_status_poll(tmp_path):
    asyncio.run(_check_thread_notification(tmp_path))


async def _check_thread_notification(tmp_path):
    settings = _configured(tmp_path)
    settings["body_analysis_enabled"] = False
    runner = tmp_path / "runner.py"
    runner.write_text("runner")
    probe_started = asyncio.Event()
    release_probe = asyncio.Event()

    async def probe(_model):
        probe_started.set()
        await release_probe.wait()
        return {"ready": False, "missing": ["dependencies"], "reason": "missing_dependencies"}

    service = BodyAnalysisJobService(root=tmp_path / "reports", settings_loader=lambda: settings,
                                     environment_probe=probe, runner_path=runner)
    service.start()
    await service.active_task
    settings["body_analysis_enabled"] = True
    await asyncio.to_thread(service.notify_settings_changed)
    await asyncio.wait_for(probe_started.wait(), timeout=5)
    assert service.status()["status"] == "checking"
    release_probe.set()
    await service.active_task
    await service.close()


def test_settings_change_during_active_scan_cancels_old_and_starts_new_without_poll(tmp_path):
    asyncio.run(_check_active_settings_restart(tmp_path))


async def _check_active_settings_restart(tmp_path):
    settings = _configured(tmp_path)
    runner = tmp_path / "runner.py"
    runner.write_text("runner")
    first_started = asyncio.Event()
    first_cancelled = asyncio.Event()
    second_started = asyncio.Event()
    calls = 0

    async def probe(_model):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                first_cancelled.set()
                raise
        second_started.set()
        return {"ready": False, "missing": ["dependencies"], "reason": "missing_dependencies"}

    service = BodyAnalysisJobService(root=tmp_path / "reports", settings_loader=lambda: settings,
                                     environment_probe=probe, runner_path=runner)
    service.start()
    await asyncio.wait_for(first_started.wait(), timeout=5)
    replacement = tmp_path / "scalp-replacement"
    replacement.mkdir()
    settings["body_analysis_scalp_dir"] = str(replacement)
    await asyncio.to_thread(service.notify_settings_changed)
    await asyncio.wait_for(second_started.wait(), timeout=5)
    assert first_cancelled.is_set()
    await service.active_task
    assert calls == 2 and service.status()["status"] == "missing_environment"
    await service.close()


def test_report_retention_is_bounded_only_after_successful_pointer_update(tmp_path, monkeypatch):
    asyncio.run(_check_report_retention(tmp_path, monkeypatch))


async def _check_report_retention(tmp_path, monkeypatch):
    settings = _configured(tmp_path)
    Path(settings["body_analysis_leg_dir"], "a.jpg").unlink()
    runner = tmp_path / "runner.py"
    runner.write_text("runner")
    root = tmp_path / "reports"
    success = {"value": True}

    async def fake_exec(*argv, **_kwargs):
        output = Path(argv[argv.index("--output-dir") + 1])
        output.mkdir()
        (output / "report.json").write_text(json.dumps(build_report([], [])))

        async def wait():
            return 0 if success["value"] else 1

        return SimpleNamespace(wait=wait, returncode=0 if success["value"] else 1)

    monkeypatch.setattr("src.services.body_analysis_jobs.asyncio.create_subprocess_exec", fake_exec)
    service = BodyAnalysisJobService(root=root, settings_loader=lambda: settings,
                                     environment_probe=lambda _: {"ready": True, "missing": [], "reason": "ready", "python_executable": "python"},
                                     runner_path=runner)
    sentinel = root / "published" / "not-generated"
    sentinel.mkdir(parents=True)
    (sentinel / "private.txt").write_text("keep")
    for _ in range(5):
        service.start(force=True)
        await service.active_task
        assert service.status()["status"] == "ready"
    generated = [item for item in (root / "published").iterdir() if re.fullmatch(r"[0-9a-f]{32}", item.name)]
    assert len(generated) == 3
    pointer = json.loads((root / "current.json").read_text())
    assert (root / "published" / pointer["directory"]).is_dir()
    assert (sentinel / "private.txt").read_text() == "keep"
    success["value"] = False
    service.start(force=True)
    await service.active_task
    assert service.status()["status"] == "failed"
    assert json.loads((root / "current.json").read_text()) == pointer
    assert len([item for item in (root / "published").iterdir() if re.fullmatch(r"[0-9a-f]{32}", item.name)]) == 3
    success["value"] = True
    monkeypatch.setattr("src.services.body_analysis_jobs._write_json_atomically",
                        lambda *_args: (_ for _ in ()).throw(OSError("pointer failed")))
    service.start(force=True)
    await service.active_task
    assert service.status()["status"] == "failed"
    assert json.loads((root / "current.json").read_text()) == pointer
    assert len([item for item in (root / "published").iterdir() if re.fullmatch(r"[0-9a-f]{32}", item.name)]) == 3
    await service.close()


def test_cancelled_optional_install_blocks_replacement_until_worker_exits(tmp_path):
    asyncio.run(_check_install_cancel_barrier(tmp_path))


async def _check_install_cancel_barrier(tmp_path):
    settings = _configured(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    exited = threading.Event()
    calls = 0

    def installer(_model, *, explicit, cancel_event):
        nonlocal calls
        calls += 1
        assert explicit is True
        if calls == 1:
            entered.set()
            release.wait(5)
            assert cancel_event.is_set()
            exited.set()
        return {"state": "missing_dependencies", "ready": False,
                "missing": ["dependencies"], "reason": "missing_dependencies"}

    service = BodyAnalysisJobService(root=tmp_path / "reports", settings_loader=lambda: settings,
                                     environment_installer=installer)
    assert await service.install()
    assert await asyncio.to_thread(entered.wait, 5)
    old_task = service.active_task
    old_task.cancel()
    await asyncio.sleep(0.05)
    assert not old_task.done()
    assert not await service.install()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await old_task
    assert exited.is_set()
    assert await service.install()
    await service.active_task
    assert calls == 2
    await service.close()


def test_validated_report_is_cached_by_pointer_and_manifest_revision(tmp_path, monkeypatch):
    from src.services import body_analysis_jobs as jobs_module

    root = tmp_path / "reports"
    folder = root / "published" / "version1"
    (folder / "masks").mkdir(parents=True)
    (folder / "masks" / "safe.png").write_bytes(b"PNG")
    report = build_report([], [])
    report["assets"] = ["masks/safe.png"]
    report_file = folder / "report.json"
    report_file.write_text(json.dumps(report))
    (root / "current.json").write_text(json.dumps({"directory": "version1", "fingerprint": "a" * 64}))
    validations = []
    original_validate = jobs_module.validate_report_manifest

    def count_validate(*args):
        validations.append(1)
        return original_validate(*args)

    monkeypatch.setattr(jobs_module, "validate_report_manifest", count_validate)
    service = BodyAnalysisJobService(root=root, settings_loader=lambda: {"body_analysis_enabled": False})
    assert service.status()["report_revision"] == "version1"
    assert service.status()["report_revision"] == "version1"
    assert service.report()["complete"] is True
    assert service.asset("masks/safe.png") is not None
    assert len(validations) == 1
    report["extra"] = "updated"
    report_file.write_text(json.dumps(report))
    changed = report_file.stat().st_mtime_ns + 10_000_000
    os.utime(report_file, ns=(changed, changed))
    assert service.report()["extra"] == "updated"
    assert len(validations) == 2
    second = root / "published" / "version2"
    second.mkdir()
    (second / "report.json").write_text(json.dumps(build_report([], [])))
    (root / "current.json").write_text(json.dumps({"directory": "version2", "fingerprint": "b" * 64}))
    assert service.status()["report_revision"] == "version2"
    assert len(validations) == 3
    (root / "current.json").write_text(json.dumps({"directory": "version1", "fingerprint": "a" * 64}))
    assert service.asset("masks/safe.png") is not None
    source = folder / "masks" / "safe.png"
    source.unlink()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"private")
    try:
        source.symlink_to(outside)
    except (OSError, NotImplementedError):
        return
    assert service.asset("masks/safe.png") is None  # target checked even on cache hit


def test_settings_change_poll_schedules_scan_once(tmp_path):
    asyncio.run(_check_settings_change(tmp_path))


async def _check_settings_change(tmp_path):
    settings = _configured(tmp_path)
    settings["body_analysis_enabled"] = False
    service = BodyAnalysisJobService(root=tmp_path / "reports", settings_loader=lambda: settings)
    service.start()
    await service.active_task
    assert service.status()["status"] == "disabled"
    settings["body_analysis_enabled"] = True
    service.refresh_on_settings_change()
    first = service.active_task
    assert first is not None
    service.refresh_on_settings_change()
    assert service.active_task is first
    await first
    await service.close()


def test_report_rejects_private_path_and_asset_symlink(tmp_path):
    root = tmp_path / "reports"
    folder = root / "published" / "version1"
    (folder / "masks").mkdir(parents=True)
    report = build_report([], [])
    report["source_dir"] = "C:/private/photos"
    (folder / "report.json").write_text(json.dumps(report))
    (root / "current.json").write_text(json.dumps({"directory": "version1", "fingerprint": "a" * 64}))
    service = BodyAnalysisJobService(root=root, settings_loader=lambda: {"body_analysis_enabled": False})
    assert service.report() is None
    report.pop("source_dir")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"private")
    link = folder / "masks" / "outside.png"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        return
    report["assets"] = ["masks/outside.png"]
    (folder / "report.json").write_text(json.dumps(report))
    assert service.asset("masks/outside.png") is None


def test_progress_is_bounded_and_contains_no_runner_text(tmp_path):
    service = BodyAnalysisJobService(root=tmp_path / "reports", settings_loader=lambda: {})
    progress = tmp_path / "progress.json"
    progress.write_text(json.dumps({"completed": 99, "total": 1, "path": "C:/private/photos"}))
    service._read_progress(progress, {"leg": 1, "scalp": 0})
    assert service._progress is None
    progress.write_text(json.dumps({"completed": 1, "total": 1, "path": "C:/private/photos"}))
    service._read_progress(progress, {"leg": 1, "scalp": 0})
    assert service._progress == {"completed": 1, "total": 1}


def test_unsafe_output_root_does_not_prevent_service_creation(monkeypatch):
    def reject_root():
        raise ValueError("private absolute path")

    monkeypatch.setattr("src.services.body_analysis_jobs.get_body_analysis_report_root", reject_root)
    service = BodyAnalysisJobService(settings_loader=lambda: {"body_analysis_enabled": True})
    assert service.status()["status"] == "failed"
    assert service.status()["error"] == "unsafe_output_root"
    assert "private" not in str(service.status())


def test_settings_change_during_run_cannot_publish_stale_report(tmp_path, monkeypatch):
    asyncio.run(_check_changed_settings_during_run(tmp_path, monkeypatch))


async def _check_changed_settings_during_run(tmp_path, monkeypatch):
    settings = _configured(tmp_path)
    Path(settings["body_analysis_leg_dir"], "a.jpg").unlink()
    runner = tmp_path / "runner.py"
    runner.write_text("runner")
    root = tmp_path / "reports"

    async def fake_exec(*argv, **kwargs):
        output = Path(argv[argv.index("--output-dir") + 1])
        output.mkdir()
        (output / "report.json").write_text(json.dumps(build_report([], [])))
        settings["body_analysis_enabled"] = False

        async def wait():
            return 0

        return SimpleNamespace(wait=wait, returncode=0)

    monkeypatch.setattr("src.services.body_analysis_jobs.asyncio.create_subprocess_exec", fake_exec)
    service = BodyAnalysisJobService(root=root, settings_loader=lambda: settings,
                                     environment_probe=lambda _: {"ready": True, "missing": [], "reason": "ready", "python_executable": "python"},
                                     runner_path=runner)
    service.start()
    await service.active_task
    assert not (root / "current.json").exists()
    service.refresh_on_settings_change()
    assert service.status()["status"] == "disabled"
    await service.close()


def test_shutdown_cancels_analysis_child_process(tmp_path, monkeypatch):
    asyncio.run(_check_shutdown_cancels_child(tmp_path, monkeypatch))


async def _check_shutdown_cancels_child(tmp_path, monkeypatch):
    settings = _configured(tmp_path)
    runner = tmp_path / "runner.py"
    runner.write_text("runner")
    release = asyncio.Event()
    created = asyncio.Event()

    class FakeProcess:
        returncode = None
        terminated = False

        async def wait(self):
            await release.wait()
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15
            release.set()

        def kill(self):
            self.terminate()

    child = FakeProcess()

    async def fake_exec(*argv, **kwargs):
        created.set()
        return child

    monkeypatch.setattr("src.services.body_analysis_jobs.asyncio.create_subprocess_exec", fake_exec)
    service = BodyAnalysisJobService(root=tmp_path / "reports", settings_loader=lambda: settings,
                                     environment_probe=lambda _: {"ready": True, "missing": [], "reason": "ready", "python_executable": "python"},
                                     runner_path=runner)
    service.start()
    await asyncio.wait_for(created.wait(), timeout=5)
    await service.close()
    assert child.terminated
    assert service.active_task.done()

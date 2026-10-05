"""Local crash evidence: never crash the running application in these tests."""
import importlib
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


def diagnostics_module():
    try:
        return importlib.import_module("src.core.crash_diagnostics")
    except ModuleNotFoundError:
        pytest.fail("local Python crash diagnostics have not been implemented")


def run_isolated(tmp_path, body):
    env = {**os.environ, "VANTAGE_DATA_DIR": str(tmp_path), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-c", "from src.core.crash_diagnostics import install_crash_diagnostics; "
         "record = install_crash_diagnostics(role='backend'); " + body],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, timeout=15,
    )


def test_uses_configured_root_and_removes_empty_clean_file(tmp_path, monkeypatch):
    module = diagnostics_module()
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path))
    record = module.install_crash_diagnostics(role="backend", periodic_seconds=0)
    assert record.path.parent == tmp_path / "diagnostics" / "python"
    assert ".active.log" in record.path.name
    record.close()
    assert not list((tmp_path / "diagnostics" / "python").iterdir())


def test_uncaught_exception_report_omits_secret_value_and_source(tmp_path):
    diagnostics_module()
    result = run_isolated(tmp_path, "raise ValueError('API_SECRET_DONOT_RECORD')")
    assert result.returncode != 0
    reports = list((tmp_path / "diagnostics" / "python").glob("*.log"))
    assert len(reports) == 1
    text = reports[0].read_text(encoding="utf-8")
    assert "ValueError" in text and "<module>" in text and "line" in text
    assert "API_SECRET_DONOT_RECORD" not in text
    assert "API_SECRET_DONOT_RECORD" not in result.stderr
    assert ".active." not in reports[0].name


def test_thread_exception_report_omits_exception_value(tmp_path):
    diagnostics_module()
    result = run_isolated(tmp_path, "import threading; "
                          "t = threading.Thread(target=lambda: (_ for _ in ()).throw(RuntimeError('THREAD_SECRET'))); "
                          "t.start(); t.join()")
    assert result.returncode == 0
    report = next((tmp_path / "diagnostics" / "python").glob("*.log"))
    text = report.read_text(encoding="utf-8")
    assert "thread-exception" in text and "RuntimeError" in text
    assert "THREAD_SECRET" not in text + result.stderr


def test_actual_fatal_fault_writes_stack_and_next_launch_recovers_it(tmp_path):
    diagnostics_module()
    # CPython's fatal-signal test helper bypasses ctypes' Windows exception wrapper.
    result = run_isolated(tmp_path, "import faulthandler; faulthandler._sigsegv()")
    assert result.returncode != 0
    report = next((tmp_path / "diagnostics" / "python").glob("*.active.log"))
    text = report.read_text(encoding="utf-8")
    assert "Current thread" in text and '<string>' in text
    assert run_isolated(tmp_path, "pass").returncode == 0
    assert not list((tmp_path / "diagnostics" / "python").glob("*.active.log"))
    assert list((tmp_path / "diagnostics" / "python").glob("*.log"))


def test_retention_preserves_active_records_and_unknown_files(tmp_path):
    module = diagnostics_module()
    root = tmp_path / "diagnostics"
    root.mkdir()
    active = root / "backend-1-abc.active.log"
    active.write_bytes(b"active")
    unknown = root / "config.json"
    unknown.write_text("unchanged")
    for index in range(12):
        path = root / f"incident-{index}.json"
        path.write_bytes(b"{}")
        os.utime(path, (index + 1, index + 1))
    module.prune_diagnostics(root, max_records=10, max_bytes=200 * 1024 * 1024)
    assert len(list(root.glob("incident-*.json"))) == 10
    assert not (root / "incident-0.json").exists()
    assert active.read_bytes() == b"active" and unknown.read_text() == "unchanged"


def test_byte_budget_counts_active_bytes_without_deleting_active(tmp_path):
    module = diagnostics_module()
    (tmp_path / "backend-1-abc.active.log").write_bytes(b"a" * 8)
    (tmp_path / "incident-1.json").write_bytes(b"x" * 4)
    module.prune_diagnostics(tmp_path, max_bytes=10)
    assert (tmp_path / "backend-1-abc.active.log").exists()
    assert not (tmp_path / "incident-1.json").exists()


def test_cleanup_never_traverses_links_or_deletes_outside_root(tmp_path):
    module = diagnostics_module()
    root = tmp_path / "diagnostics"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    victim = outside / "incident-private.json"
    victim.write_bytes(b"private")
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
        (root / "incident-link.json").symlink_to(victim)
    except OSError:
        pytest.skip("symlink creation unavailable")
    module.prune_diagnostics(root, max_records=0, max_bytes=0)
    assert victim.read_bytes() == b"private"
    assert (root / "incident-link.json").is_symlink()


def test_storage_failure_does_not_prevent_startup(tmp_path, monkeypatch):
    module = diagnostics_module()
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path))
    (tmp_path / "diagnostics").write_text("not a directory")
    assert module.install_crash_diagnostics(periodic_seconds=0) is None


def test_live_active_file_is_not_recovered(tmp_path):
    module = diagnostics_module()
    root = tmp_path / "python"
    root.mkdir()
    path = root / f"backend-{os.getpid()}-existing.active.log"
    path.write_text("live")
    module.recover_stale_python_records(root)
    assert path.exists()


def test_entry_points_initialize_before_service_imports():
    diagnostics_module()
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "src/scripts/run_server_background.py").read_text(encoding="utf-8")
    prompt = (root / "src/scripts/run_prompt.py").read_text(encoding="utf-8")
    assert launcher.index("install_crash_diagnostics(") < launcher.index("from src.utils.sensitive_data")
    assert prompt.index("install_crash_diagnostics(") < prompt.index("from src.services.llm_client")


def test_retention_protects_recent_native_dump_while_counting_bytes(tmp_path):
    module = diagnostics_module()
    native = tmp_path / "collector.dmp"
    native.write_bytes(b"n" * 8)
    completed = tmp_path / "incident-1.json"
    completed.write_bytes(b"x" * 4)
    module.prune_diagnostics(tmp_path, max_bytes=10)
    assert native.exists() and not completed.exists()
    os.utime(native, (1, 1))
    module.prune_diagnostics(tmp_path, max_bytes=0)
    assert not native.exists()


def test_failed_native_handler_setup_closes_and_removes_file(tmp_path, monkeypatch):
    module = diagnostics_module()
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path))
    def fail(**kwargs):
        raise OSError("storage unavailable")
    monkeypatch.setattr(module.faulthandler, "enable", fail)
    assert module.install_crash_diagnostics(periodic_seconds=0) is None
    assert not list((tmp_path / "diagnostics" / "python").iterdir())


def test_periodic_cleanup_enforces_count_without_closing_active_log(tmp_path, monkeypatch):
    module = diagnostics_module()
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path))
    record = module.install_crash_diagnostics(periodic_seconds=0.01)
    try:
        for index in range(12):
            (record.root / f"incident-{index}.json").write_text("{}")
        deadline = time.monotonic() + 2
        while len(list(record.root.glob("incident-*.json"))) > 10 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(list(record.root.glob("incident-*.json"))) <= 10
        assert record.path.exists() and not record.handle.closed
    finally:
        record.close()


def test_install_is_idempotent_and_close_restores_exception_hooks(tmp_path, monkeypatch):
    module = diagnostics_module()
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path))
    old_sys, old_thread = sys.excepthook, module.threading.excepthook
    record = module.install_crash_diagnostics(periodic_seconds=0)
    assert module.install_crash_diagnostics(periodic_seconds=0) is record
    record.close()
    record.close()
    assert sys.excepthook is old_sys and module.threading.excepthook is old_thread


def test_stale_recovery_rechecks_root_for_link_swap(tmp_path, monkeypatch):
    module = diagnostics_module()
    outside = tmp_path / "private"
    (outside / "nested").mkdir(parents=True)
    victim = outside / "nested" / "backend-12345-test.active.log"
    victim.write_text("private evidence")
    root = tmp_path / "python"
    try:
        root.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    # Simulate a scan performed just before an ancestor is swapped for a link.
    path = root / "nested" / victim.name
    monkeypatch.setattr(module, "_walk_regular_files", lambda _: iter([(path, victim.lstat())]))
    monkeypatch.setattr(module, "_process_alive", lambda _: False)
    module.recover_stale_python_records(root)
    assert victim.exists()
    assert not (outside / "nested" / "backend-12345-test.log").exists()


def test_retention_preserves_file_updated_after_enumeration(tmp_path, monkeypatch):
    module = diagnostics_module()
    report = tmp_path / "incident-changing.json"
    report.write_text("old")
    snapshot = report.lstat()
    report.write_text("new and still growing")
    monkeypatch.setattr(module, "_walk_regular_files", lambda _: iter([(report, snapshot)]))
    module.prune_diagnostics(tmp_path, max_records=0, max_bytes=0)
    assert report.read_text() == "new and still growing"


def test_stale_recovery_preserves_file_updated_after_enumeration(tmp_path, monkeypatch):
    module = diagnostics_module()
    report = tmp_path / "backend-12345-changing.active.log"
    report.write_text("old")
    snapshot = report.lstat()
    report.write_text("new and still growing")
    monkeypatch.setattr(module, "_walk_regular_files", lambda _: iter([(report, snapshot)]))
    monkeypatch.setattr(module, "_process_alive", lambda _: False)
    module.recover_stale_python_records(tmp_path)
    assert report.read_text() == "new and still growing"


def test_retention_preserves_aged_crashpad_new_dump_until_finalized(tmp_path):
    module = diagnostics_module()
    writing = tmp_path / "electron" / "new" / "writer.dmp"
    writing.parent.mkdir(parents=True)
    writing.write_bytes(b"still open")
    old_time = time.time() - 120
    os.utime(writing, (old_time, old_time))
    module.prune_diagnostics(tmp_path, max_records=0, max_bytes=0)
    assert writing.exists()
    pending = tmp_path / "electron" / "pending" / "writer.dmp"
    pending.parent.mkdir()
    writing.rename(pending)
    module.prune_diagnostics(tmp_path, max_records=0, max_bytes=0)
    assert not pending.exists()


@pytest.mark.parametrize("use_explicit_directory", [False, True])
def test_standalone_frozen_entry_uses_user_directory_not_install_resources(tmp_path, use_explicit_directory):
    env = dict(os.environ)
    for name in ("VANTAGE_APP_MODE", "VANTAGE_DATA_DIR", "VANTAGE_PROJECT_ROOT"):
        env.pop(name, None)
    env["LOCALAPPDATA"] = str(tmp_path / "user")
    if use_explicit_directory:
        env["VANTAGE_DATA_DIR"] = str(tmp_path / "custom-data")
    resource_root = tmp_path / "installation"
    body = (
        "import sys; from pathlib import Path; "
        "from src.scripts import run_server_background as launcher; "
        f"sys.frozen = True; sys._MEIPASS = {str(resource_root)!r}; "
        "launcher._initialize_packaged_app_mode(); "
        "record = launcher.install_crash_diagnostics(role='cli', periodic_seconds=0); "
        "print(record.path); record.close()"
    )
    result = subprocess.run([sys.executable, "-c", body], env=env,
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    expected_root = tmp_path / "custom-data" if use_explicit_directory else tmp_path / "user" / "Vantage"
    assert str(expected_root / "diagnostics" / "python") in result.stdout
    assert not resource_root.exists()


def test_packaged_entry_mode_initialization_respects_explicit_overrides():
    from src.scripts import run_server_background as launcher
    assert hasattr(launcher, "_initialize_packaged_app_mode"), "missing packaged entry mode initialization"
    explicit = {"VANTAGE_APP_MODE": "development", "VANTAGE_DATA_DIR": "custom-location"}
    launcher._initialize_packaged_app_mode(env=explicit, is_frozen=True)
    assert explicit == {"VANTAGE_APP_MODE": "development", "VANTAGE_DATA_DIR": "custom-location"}
    development = {}
    launcher._initialize_packaged_app_mode(env=development, is_frozen=False)
    assert development == {}
    packaged = {"VANTAGE_DATA_DIR": "custom-location"}
    launcher._initialize_packaged_app_mode(env=packaged, is_frozen=True)
    assert packaged == {"VANTAGE_APP_MODE": "packaged", "VANTAGE_DATA_DIR": "custom-location"}


def test_packaged_mode_is_initialized_before_diagnostics():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "src/scripts/run_server_background.py").read_text(encoding="utf-8")
    assert "    _initialize_packaged_app_mode()" in launcher
    assert launcher.index("    _initialize_packaged_app_mode()") < launcher.index("install_crash_diagnostics(role=_role)")

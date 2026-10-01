from src.scripts import run_server_background as launcher


def test_normal_app_launch_has_no_diagnostic_thread():
    assert launcher._start_isolated_stack_diagnostics(env={}) is None
    assert launcher._start_isolated_stack_diagnostics(env={"VANTAGE_RUNTIME_STACK_DIAGNOSTICS": "1"}) is None


def test_isolated_diagnostics_write_only_to_explicit_runtime_directory(monkeypatch, tmp_path):
    calls = []
    cleanup = []
    monkeypatch.setattr(launcher.faulthandler, "enable", lambda **kwargs: calls.append(("enable", kwargs)))
    monkeypatch.setattr(launcher.faulthandler, "dump_traceback_later", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(launcher.faulthandler, "cancel_dump_traceback_later", lambda: calls.append(("cancel", {})))
    monkeypatch.setattr(launcher.faulthandler, "disable", lambda: calls.append(("disable", {})))
    monkeypatch.setattr(launcher.atexit, "register", cleanup.append)
    handle = launcher._start_isolated_stack_diagnostics(env={
        "VANTAGE_RUNTIME_STACK_DIAGNOSTICS": "1", "VANTAGE_RUNTIME_DIR": str(tmp_path),
    })
    assert handle.name.startswith(str(tmp_path))
    assert calls[1][0] == (30,)
    assert calls[1][1]["repeat"] is True
    cleanup[0]()
    assert handle.closed

import io
import sys

import debug_suite


class _FakeProcess:
    def __init__(self):
        self.terminated = False
        self.waited = False

    def terminate(self):
        self.terminated = True

    def wait(self):
        self.waited = True


def test_debug_suite_main_handles_gbk_stdout(monkeypatch):
    stream = io.TextIOWrapper(io.BytesIO(), encoding="gbk")
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(debug_suite, "is_port_in_use", lambda port: True)
    monkeypatch.setattr(debug_suite, "wait_for_server", lambda timeout=5: False)

    debug_suite.main()


def test_debug_suite_main_waits_sixty_seconds_for_backend_startup(monkeypatch):
    fake_process = _FakeProcess()
    wait_calls = []

    def fake_wait_for_server(timeout=10):
        wait_calls.append(timeout)
        return True

    monkeypatch.setattr(debug_suite, "is_port_in_use", lambda port: False)
    monkeypatch.setattr(debug_suite, "start_server", lambda: fake_process)
    monkeypatch.setattr(debug_suite, "wait_for_server", fake_wait_for_server)
    monkeypatch.setattr(debug_suite, "test_api", lambda *args, **kwargs: True)

    debug_suite.main()

    assert wait_calls == [60]
    assert fake_process.terminated is True


def test_debug_suite_main_waits_long_enough_for_existing_server(monkeypatch):
    stream = io.TextIOWrapper(io.BytesIO(), encoding="gbk")
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(debug_suite, "is_port_in_use", lambda port: True)

    observed_timeouts = []

    def fake_wait_for_server(timeout=10):
        observed_timeouts.append(timeout)
        return True

    monkeypatch.setattr(debug_suite, "wait_for_server", fake_wait_for_server)
    monkeypatch.setattr(debug_suite, "test_api", lambda *args, **kwargs: True)

    debug_suite.main()

    assert observed_timeouts == [60]

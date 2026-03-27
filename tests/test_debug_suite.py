import io
import sys

import debug_suite


def test_debug_suite_main_handles_gbk_stdout(monkeypatch):
    stream = io.TextIOWrapper(io.BytesIO(), encoding="gbk")
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(debug_suite, "is_port_in_use", lambda port: True)
    monkeypatch.setattr(debug_suite, "wait_for_server", lambda timeout=5: False)

    debug_suite.main()

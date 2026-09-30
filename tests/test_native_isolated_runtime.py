from pathlib import Path
from types import SimpleNamespace

import pytest

from src.scripts import verify_backend_runtime as verifier


def test_isolated_smoke_strips_credentials_and_inherited_data(monkeypatch, tmp_path):
    monkeypatch.setenv("VANTAGE_CONFIG_DIR", "/private/config")
    monkeypatch.setenv("VANTAGE_HISTORY_DIR", "/private/history")
    monkeypatch.setenv("VANTAGE_BACKEND_URL", "http://localhost:9234/proxy")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-secret")
    monkeypatch.setenv("CLIPROXYAPI_API_KEY", "fixture-secret")
    monkeypatch.setenv("UNRELATED_ACCESS_TOKEN", "fixture-secret")
    layout = {"build_root": tmp_path / "build", "runtime_dir": tmp_path / "runtime"}
    data = tmp_path / "unique-data"
    env = verifier._build_smoke_environment(layout, smoke_data_dir=data, isolated_port=12345)
    assert not any("fixture-secret" == value for value in env.values())
    assert env["VANTAGE_BACKEND_URL"] == "http://127.0.0.1:12345"
    assert env["VANTAGE_BACKEND_PORT"] == "12345"
    assert env["VANTAGE_RUNTIME_STACK_DIAGNOSTICS"] == "1"
    for key in ["DATA", "CONFIG", "HISTORY", "LOG", "PLOT", "CACHE", "RUNTIME", "MIGRATION"]:
        assert Path(env[f"VANTAGE_{key}_DIR"]).is_relative_to(data)


def test_isolated_flag_is_explicit():
    assert verifier._build_parser().parse_args(["--isolated"]).isolated


def test_status_uses_selected_smoke_port(monkeypatch):
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self):
            return b'{"status":"ok"}'

    def urlopen(url, **_kwargs):
        calls.append(url)
        return Response()

    monkeypatch.setattr(verifier.urllib.request, "urlopen", urlopen)
    assert verifier._wait_for_status(1, "http://127.0.0.1:12345") == {"status": "ok"}
    assert calls == ["http://127.0.0.1:12345/api/v1/system/status"]


def test_early_backend_exit_is_reported_without_waiting_full_deadline(monkeypatch):
    monkeypatch.setattr(verifier.urllib.request, "urlopen", lambda *_args, **_kwargs: pytest.fail("must detect process exit first"))
    process = SimpleNamespace(poll=lambda: -9, returncode=-9)
    with pytest.raises(RuntimeError, match="exit=-9"):
        verifier._wait_for_status(120, process=process)

from pathlib import Path

import pytest

from scripts.smoke_native_client import REQUIRED_PAGES, isolated_environment, validate_report


def report():
    return {"success": True, "errors": [], "pages": [{"id": key, "loaded": True} for key in REQUIRED_PAGES]}


def test_complete_native_report_is_required():
    validate_report(report())


@pytest.mark.parametrize("change", ["failed", "errors", "missing", "unloaded"])
def test_partial_native_report_cannot_pass(change):
    value = report()
    if change == "failed":
        value["success"] = False
    elif change == "errors":
        value["errors"] = ["failed request"]
    elif change == "missing":
        value["pages"].pop()
    else:
        value["pages"][0]["loaded"] = False
    with pytest.raises(ValueError):
        validate_report(value)


def test_native_smoke_cannot_inherit_user_data_or_model_keys(monkeypatch):
    monkeypatch.setenv("VANTAGE_CONFIG_DIR", "/private/data")
    monkeypatch.setenv("VANTAGE_BACKEND_EXECUTABLE", "/private/backend")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-secret")
    env = isolated_environment("http://127.0.0.1:12345", Path("/fixture"))
    assert env["VANTAGE_BACKEND_URL"] == "http://127.0.0.1:12345"
    assert env["VANTAGE_CONFIG_DIR"] == str(Path("/fixture/config"))
    assert "VANTAGE_BACKEND_EXECUTABLE" not in env
    assert "OPENAI_API_KEY" not in env

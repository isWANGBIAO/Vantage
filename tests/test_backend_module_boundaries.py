"""Composition and direct domain-import contracts for the backend."""
import ast
import asyncio
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.backend import camera as _backend_camera
from src.backend import runtime as _backend_runtime
from src import server
from src.backend import application, camera, chat, plots, providers, runtime, settings

ROOT = Path(__file__).resolve().parents[1]


def test_server_is_only_a_composition_root():
    source = (ROOT / "src/server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert functions == ["main"]
    assert len(source.splitlines()) < 200
    for module in server.ROUTE_MODULES:
        assert module.router.routes
        for route in module.router.routes:
            assert route.endpoint.__module__ == module.__name__


def test_public_http_api_uses_only_the_canonical_namespace():
    paths = server.app.openapi()["paths"]
    assert "/api/v1/action-plan/jobs" in paths
    assert "/api/v1/action-plan/today" in paths
    assert all(not path.startswith("/api/") or path.startswith("/api/v1/") for path in paths)
    assert "/api/action_plan" not in paths
    assert "/api/action_plan_content" not in paths
    assert "/api/automation/settings" not in paths


def test_backend_domains_do_not_import_the_legacy_server():
    for path in (ROOT / "src/backend").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name != "src.server" for alias in node.names), path
            if isinstance(node, ast.ImportFrom):
                assert node.module != "src.server", path
                if node.module == "src":
                    assert all(alias.name != "server" for alias in node.names), path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"exec", "eval", "compile"}, path


def test_domains_import_without_composing_the_http_app():
    result = subprocess.run(
        [sys.executable, "-c", (
            "import src.backend.camera, src.backend.settings, src.backend.finance_data; "
            "import sys; assert 'src.server' not in sys.modules"
        )],
        cwd=ROOT, check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_server_does_not_reexport_domain_functions_or_mutable_state():
    for name in ("ChatRequest", "get_camera_index", "startup_event", "update_automation_settings",
                 "load_settings", "_cv2_module", "_plot_dashboard_cache_key", "state",
                 "_legacy_export_owners"):
        assert not hasattr(server, name), name
    assert not (ROOT / "src/backend/compat.py").exists()
    assert camera.get_camera_index.__globals__ is vars(camera)


def test_dependency_overrides_are_scoped_to_the_domain_owner(monkeypatch):
    original_provider_settings = providers.load_settings
    fake_settings = lambda: {"display_language": "en-US"}
    monkeypatch.setattr(settings, "load_settings", fake_settings)
    assert settings.load_settings is fake_settings
    assert providers.load_settings is original_provider_settings
    assert settings.get_automation_display_language() == {"display_language": "en-US"}


def test_direct_domain_patch_restores_original_value():
    original = camera._cv2_module
    replacement = object()
    with patch.object(camera, "_cv2_module", replacement):
        assert camera._cv2_module is replacement
    assert camera._cv2_module is original
    assert not hasattr(server, "_cv2_module")


def test_mutable_domain_globals_remain_owned_by_the_domain(monkeypatch):
    marker = object()
    monkeypatch.setattr(plots, "_plot_dashboard_cache_key", marker)
    assert plots._plot_dashboard_cache_key is marker
    assert "_plot_dashboard_cache_key" not in vars(server)
    replacement = object()
    with patch.object(plots, "_plot_dashboard_cache_key", replacement):
        assert plots._plot_dashboard_cache_key is replacement
    assert plots._plot_dashboard_cache_key is marker


def test_http_routes_execute_the_domain_code(monkeypatch):
    monkeypatch.setattr(_backend_camera, "_camera_online", lambda: False)
    monkeypatch.setattr(_backend_camera, "_build_camera_frame_diagnostics", lambda: {
        "available": False, "dark": False, "mean_luma": None,
    })
    response = TestClient(server.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345)).get("/api/v1/system/status")
    assert response.status_code == 200
    assert response.json()["camera_online"] is False
    assert "/api/v1/settings" in server.app.openapi()["paths"]


@pytest.mark.parametrize("path", ["/api/v1/settings", "/api/v1/capabilities"])
def test_private_api_rejects_non_loopback_clients(path):
    response = TestClient(server.app, base_url="http://127.0.0.1:8000", client=("203.0.113.10", 50000)).get(path)
    assert response.status_code == 403


@pytest.mark.parametrize("start_fails", [False, True])
def test_lifespan_owns_application_and_hardware_cleanup(monkeypatch, start_fails):
    calls = []

    async def start_hardware():
        calls.append("hardware-start")

    async def start_application():
        calls.append("application-start")
        if start_fails:
            raise RuntimeError("startup failed")

    async def stop_application():
        calls.append("application-stop")

    async def stop_hardware():
        calls.append("hardware-stop")

    monkeypatch.setattr(_backend_runtime, "startup_event", start_hardware)
    monkeypatch.setattr(_backend_runtime, "shutdown_event", stop_hardware)
    monkeypatch.setattr(application, "start", start_application)
    monkeypatch.setattr(application, "stop", stop_application)

    async def exercise():
        async with runtime.lifespan(server.app):
            calls.append("serving")

    if start_fails:
        with pytest.raises(RuntimeError, match="startup failed"):
            asyncio.run(exercise())
    else:
        asyncio.run(exercise())
    expected = ["hardware-start", "application-start"]
    if not start_fails:
        expected.append("serving")
    assert calls == [*expected, "application-stop", "hardware-stop"]


def test_main_uses_the_shared_backend_address(monkeypatch):
    monkeypatch.setenv("VANTAGE_BACKEND_URL", "http://127.0.0.1:8123")
    with patch("uvicorn.run") as run:
        server.main()
    run.assert_called_once_with(server.app, host="127.0.0.1", port=8123, access_log=False)


@pytest.mark.parametrize('origin', ['https://untrusted.example', 'null', 'http://localhost.attacker.example:5173'])
@pytest.mark.parametrize('path', ['/api/v1/action-plan/jobs', '/api/v1/action-plan/jobs/missing/cancel', '/api/v1/settings'])
def test_mutations_reject_cross_site_browser_origins_before_dispatch(origin, path):
    # Do not enter the lifespan: this transport test must never start hardware.
    client = TestClient(server.app, base_url="http://127.0.0.1:8000", client=('127.0.0.1', 12345))
    response = client.post(path, headers={'Origin': origin, 'Host': '127.0.0.1:8000'}, content='')
    assert response.status_code == 403
    assert response.json()['error'] == 'Untrusted browser origin'


@pytest.mark.parametrize('origin', [None, 'http://127.0.0.1:5173'])
def test_native_and_trusted_browser_can_read_versioned_contract(origin):
    headers = {'Host': '127.0.0.1:8000'}
    if origin is not None:
        headers['Origin'] = origin
    response = TestClient(server.app, base_url="http://127.0.0.1:8000", client=('127.0.0.1', 12345)).get('/api/v1/capabilities', headers=headers)
    assert response.status_code == 200
    assert response.json()['api_version'] == '1.0'

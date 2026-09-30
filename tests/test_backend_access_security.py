"""The local IPC boundary applies before any API/media/WebSocket dispatch."""
import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect

from src.backend.security import LoopbackAccessMiddleware


@pytest.fixture
def protected_app(tmp_path):
    app = FastAPI()
    app.add_middleware(LoopbackAccessMiddleware)
    calls = []

    @app.api_route("/api/test", methods=["GET", "POST"])
    async def endpoint():
        calls.append("http")
        return {"ok": True}

    @app.websocket("/ws/test")
    async def websocket_endpoint(websocket: WebSocket):
        calls.append("websocket")
        await websocket.accept()
        await websocket.send_text("ready")
        await websocket.close()

    (tmp_path / "synthetic.jpg").write_bytes(b"synthetic private image")
    app.mount("/static/photos", StaticFiles(directory=tmp_path))
    return app, calls


@pytest.mark.parametrize("path", ["/api/test", "/static/photos/synthetic.jpg", "/openapi.json"])
@pytest.mark.parametrize("headers", [
    {"Origin": "https://untrusted.invalid"},
    {"Origin": "null"},
    {"Host": "untrusted.invalid:8000"},
    {"Sec-Fetch-Site": "cross-site"},
])
def test_all_http_and_media_routes_reject_untrusted_sources(protected_app, path, headers):
    app, calls = protected_app
    response = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345)).get(
        path, headers=headers,
    )
    assert response.status_code == 403
    assert calls == []
    assert b"synthetic private image" not in response.content


@pytest.mark.parametrize("host", ["testserver", "testclient", "localhost.untrusted.invalid"])
def test_test_transport_aliases_are_not_production_loopback_hosts(protected_app, host):
    app, calls = protected_app
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345))
    assert client.get("/api/test", headers={"Host": host}).status_code == 403
    assert calls == []


@pytest.mark.parametrize("path", ["/api/test", "/static/photos/synthetic.jpg"])
def test_remote_peer_cannot_use_forged_local_host(protected_app, path):
    app, calls = protected_app
    response = TestClient(app, base_url="http://127.0.0.1:8000", client=("192.0.2.1", 12345)).get(path)
    assert response.status_code == 403
    assert calls == []


@pytest.mark.parametrize("headers", [
    {},  # Native UI and the vetted desktop scheme proxy send no Origin.
    {"Origin": "http://localhost:5173"},
    {"Origin": "http://127.0.0.1:5173", "Sec-Fetch-Site": "cross-site"},
])
def test_native_and_trusted_dev_frontends_can_use_http_and_media(protected_app, headers):
    app, calls = protected_app
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345))
    assert client.post("/api/test", headers=headers).status_code == 200
    assert client.get("/static/photos/synthetic.jpg", headers=headers).content == b"synthetic private image"
    assert calls == ["http"]


@pytest.mark.parametrize("headers", [
    [("Origin", "http://localhost:5173"), ("Origin", "https://untrusted.invalid")],
    [("Host", "127.0.0.1:8000"), ("Host", "untrusted.invalid:8000")],
])
def test_ambiguous_source_headers_are_rejected(protected_app, headers):
    app, calls = protected_app
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345))
    assert client.get("/api/test", headers=headers).status_code == 403
    assert calls == []


@pytest.mark.parametrize("headers,peer", [
    ({"Origin": "https://untrusted.invalid"}, "127.0.0.1"),
    ({"Host": "untrusted.invalid:8000"}, "127.0.0.1"),
    ({}, "192.0.2.1"),
])
def test_websocket_rejected_before_accept(protected_app, headers, peer):
    app, calls = protected_app
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=(peer, 12345))
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect("ws://127.0.0.1:8000/ws/test", headers=headers):
            pytest.fail("Untrusted WebSocket was accepted")
    assert error.value.code == 1008
    assert calls == []


@pytest.mark.parametrize("headers", [{}, {"Origin": "http://localhost:5173"}])
def test_native_and_trusted_websocket_clients_remain_supported(protected_app, headers):
    app, calls = protected_app
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345))
    with client.websocket_connect("ws://127.0.0.1:8000/ws/test", headers=headers) as websocket:
        assert websocket.receive_text() == "ready"
    assert calls == ["websocket"]


def test_composition_registers_global_boundary_before_dispatch():
    from src import server

    # No lifespan: never start camera, background tasks, or real providers.
    assert any(middleware.cls is LoopbackAccessMiddleware for middleware in server.app.user_middleware)
    client = TestClient(server.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345))
    for route in server.app.routes:
        path = getattr(route, "path", None)
        if path:
            response = client.get(path, headers={"Origin": "https://untrusted.invalid"})
            assert response.status_code == 403, path

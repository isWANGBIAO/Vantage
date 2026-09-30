from src.backend import runtime as _backend_runtime
from src.backend import security as _backend_security
from src.backend import system as _backend_system
from src import server


def test_server_uses_lifespan_instead_of_legacy_on_event_hooks():
    assert server.app.router.on_startup == []
    assert server.app.router.on_shutdown == []


def test_backend_bind_host_defaults_to_loopback():
    assert _backend_security._get_backend_bind_host({}) == "127.0.0.1"


def test_status_payload_does_not_expose_absolute_paths():
    original_paths = dict(_backend_runtime.state.paths)
    original_photos_path = _backend_runtime.state.photos_path
    original_screenshots_path = _backend_runtime.state.screenshots_path

    try:
        _backend_runtime.state.paths = {
            "photo": r"C:\Users\Example\Pictures\photo.jpg",
            "screenshot": r"C:\Users\Example\Pictures\screen.png",
        }
        _backend_runtime.state.photos_path = r"C:\Users\Example\Pictures\photos"
        _backend_runtime.state.screenshots_path = r"C:\Users\Example\Pictures\screenshots"

        payload = _backend_system._build_status_payload()
    finally:
        _backend_runtime.state.paths = original_paths
        _backend_runtime.state.photos_path = original_photos_path
        _backend_runtime.state.screenshots_path = original_screenshots_path

    payload_text = str(payload)
    assert r"C:\Users\Example" not in payload_text
    assert payload["paths"]["photo"] is True
    assert payload["paths"]["screenshot"] is True
    assert "photos_path" not in payload
    assert "screenshots_path" not in payload
    assert "cwd" not in payload


def test_dangerous_local_actions_require_intent_header():
    assert _backend_security._has_local_action_intent({"x-vantage-intent": "open-folder"}, "open-folder")
    assert not _backend_security._has_local_action_intent({}, "open-folder")
    assert not _backend_security._has_local_action_intent({"x-vantage-intent": "other"}, "open-folder")

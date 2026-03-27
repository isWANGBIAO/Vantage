from src import server


def test_server_uses_lifespan_instead_of_legacy_on_event_hooks():
    assert server.app.router.on_startup == []
    assert server.app.router.on_shutdown == []

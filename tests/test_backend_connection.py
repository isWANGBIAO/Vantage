import pytest

from src.core.backend_connection import backend_bind_address, resolve_backend_url
from src.services.vantage_client import VantageClient


def test_connection_precedence_and_ipv6():
    env = {"VANTAGE_BACKEND_URL": "http://localhost:8123", "VANTAGE_BACKEND_PORT": "8999"}
    assert resolve_backend_url(env=env) == "http://localhost:8123"
    assert resolve_backend_url("http://127.0.0.1:8222", env=env).endswith(":8222")
    assert backend_bind_address(env=env) == ("localhost", 8123)
    assert resolve_backend_url(env={"VANTAGE_BACKEND_HOST": "::1"}) == "http://[::1]:8000"


@pytest.mark.parametrize("url", ["http://local\nhost:8000", "http://localhost\\evil:8000", "http://example.org", "http://0.0.0.0:8000", "http://127.0.0.1:0",
                                "http://user:secret@localhost", "http://localhost?q=1", "file:///tmp/test"])
def test_connection_rejects_nonlocal_or_ambiguous_urls(url):
    with pytest.raises(ValueError):
        resolve_backend_url(url)


@pytest.mark.parametrize("url", ["https://localhost:8443", "http://localhost:8000/proxy"])
def test_external_local_proxy_is_connectable_but_not_hostable(url):
    assert resolve_backend_url(url) == url
    with pytest.raises(ValueError, match="already running"):
        backend_bind_address(env={"VANTAGE_BACKEND_URL": url})


def test_cli_client_uses_canonical_environment(monkeypatch):
    monkeypatch.setenv("VANTAGE_BACKEND_URL", "http://127.0.0.1:8123")
    assert VantageClient().base_url == "http://127.0.0.1:8123"
    assert VantageClient("http://127.0.0.1:8222").base_url == "http://127.0.0.1:8222"

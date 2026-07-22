import asyncio
import inspect
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src import server
from src.services.location_trust import LocationSample, LocationTrustResolver


UNAVAILABLE_KEYS = {"aqi", "city", "level", "color", "status", "lat", "lon"}


def current_timestamp_ms(**delta):
    return (datetime.now(timezone.utc) + timedelta(**delta)).timestamp() * 1_000


def successful_response(aqi=42):
    return SimpleNamespace(
        ok=True,
        status_code=200,
        json=lambda: {"current": {"us_aqi": aqi}},
    )


def backend_sample(**overrides):
    values = {
        "latitude": 39.9042,
        "longitude": 116.4074,
        "accuracy_m": 25.0,
        "captured_at": datetime.now(timezone.utc),
        "source": "satellite",
    }
    values.update(overrides)
    return LocationSample(**values)


@pytest.fixture(autouse=True)
def isolated_aqi_location_dependencies(monkeypatch):
    monkeypatch.setattr(
        server,
        "_AQI_LOCATION_TRUST_RESOLVER",
        LocationTrustResolver(),
        raising=False,
    )
    backend_location = AsyncMock(return_value=None)
    monkeypatch.setattr(
        server,
        "get_trusted_location_sample_async",
        backend_location,
        raising=False,
    )
    upstream = Mock(side_effect=AssertionError("untrusted location reached upstream"))
    monkeypatch.setattr(server.requests, "get", upstream)
    return backend_location, upstream


def run_aqi(**kwargs):
    return asyncio.run(server.get_aqi_stats(**kwargs))


def assert_location_unavailable(payload):
    assert UNAVAILABLE_KEYS <= payload.keys()
    assert payload["aqi"] is None
    assert payload["city"] == "Location unavailable"
    assert payload["level"] == "Unavailable"
    assert payload["color"] == "#b2bec3"
    assert payload["status"] == "unavailable"
    assert payload["lat"] is None
    assert payload["lon"] is None


def test_aqi_endpoint_accepts_browser_accuracy_and_timestamp_metadata():
    parameters = inspect.signature(server.get_aqi_stats).parameters

    assert "accuracy" in parameters
    assert "timestamp_ms" in parameters


def test_missing_trusted_location_fails_closed_without_upstream(
    isolated_aqi_location_dependencies,
):
    backend_location, upstream = isolated_aqi_location_dependencies

    payload = run_aqi()

    assert_location_unavailable(payload)
    backend_location.assert_awaited_once()
    upstream.assert_not_called()


@pytest.mark.parametrize(
    "browser_parameters",
    [
        {"lat": 31.2304, "lon": 121.4737},
        {
            "lat": 31.2304,
            "lon": 121.4737,
            "accuracy": 25.0,
        },
        {
            "lat": 31.2304,
            "lon": 121.4737,
            "timestamp_ms": current_timestamp_ms(),
        },
    ],
)
def test_incomplete_browser_metadata_is_rejected_without_upstream(
    browser_parameters,
    isolated_aqi_location_dependencies,
):
    backend_location, upstream = isolated_aqi_location_dependencies

    payload = run_aqi(**browser_parameters)

    assert_location_unavailable(payload)
    backend_location.assert_not_awaited()
    upstream.assert_not_called()


@pytest.mark.parametrize(
    "browser_parameters",
    [
        {
            "lat": 31.2304,
            "lon": 121.4737,
            "accuracy": 1_000.1,
            "timestamp_ms": current_timestamp_ms(),
        },
        {
            "lat": 31.2304,
            "lon": 121.4737,
            "accuracy": 25.0,
            "timestamp_ms": current_timestamp_ms(seconds=-121),
        },
        {
            "lat": 31.2304,
            "lon": 121.4737,
            "accuracy": 25.0,
            "timestamp_ms": current_timestamp_ms(hours=1),
        },
        {
            "lat": 91.0,
            "lon": 121.4737,
            "accuracy": 25.0,
            "timestamp_ms": current_timestamp_ms(),
        },
        {
            "lat": 31.2304,
            "lon": 181.0,
            "accuracy": 25.0,
            "timestamp_ms": current_timestamp_ms(),
        },
        {
            "lat": float("nan"),
            "lon": 121.4737,
            "accuracy": 25.0,
            "timestamp_ms": current_timestamp_ms(),
        },
        {
            "lat": 31.2304,
            "lon": 121.4737,
            "accuracy": 25.0,
            "timestamp_ms": float("inf"),
        },
    ],
)
def test_untrusted_browser_samples_fail_closed_without_upstream(
    browser_parameters,
    isolated_aqi_location_dependencies,
):
    backend_location, upstream = isolated_aqi_location_dependencies

    payload = run_aqi(**browser_parameters)

    assert_location_unavailable(payload)
    backend_location.assert_not_awaited()
    upstream.assert_not_called()


def test_browser_sample_without_backend_fails_closed_without_upstream(
    isolated_aqi_location_dependencies,
    capsys,
):
    backend_location, _ = isolated_aqi_location_dependencies
    payload = run_aqi(
        lat=31.2304,
        lon=121.4737,
        accuracy=1_000.0,
        timestamp_ms=current_timestamp_ms(),
    )

    assert_location_unavailable(payload)
    backend_location.assert_awaited_once()
    upstream = server.requests.get
    upstream.assert_not_called()
    output = capsys.readouterr().out
    assert "31.2304" not in output
    assert "121.4737" not in output


def test_backend_trusted_location_is_used_when_browser_is_missing(
    monkeypatch,
    isolated_aqi_location_dependencies,
):
    backend_location, _ = isolated_aqi_location_dependencies
    backend_location.return_value = backend_sample()
    upstream = Mock(return_value=successful_response(88))
    monkeypatch.setattr(server.requests, "get", upstream)

    payload = run_aqi()

    assert payload["status"] == "ok"
    assert payload["city"] == "Current Location"
    assert payload["lat"] == 39.9042
    assert payload["lon"] == 116.4074
    backend_location.assert_awaited_once()
    purpose = backend_location.await_args.args[0]
    assert purpose.value == "aqi"
    assert "latitude=39.9042" in upstream.call_args.args[0]
    assert "longitude=116.4074" in upstream.call_args.args[0]


def test_invalid_browser_sample_does_not_fallback_to_trusted_backend(
    isolated_aqi_location_dependencies,
):
    backend_location, _ = isolated_aqi_location_dependencies
    backend_location.return_value = backend_sample()

    payload = run_aqi(
        lat=31.2304,
        lon=121.4737,
        accuracy=1_000.1,
        timestamp_ms=current_timestamp_ms(),
    )

    assert_location_unavailable(payload)
    backend_location.assert_not_awaited()
    server.requests.get.assert_not_called()


def test_matching_browser_and_backend_uses_backend_coordinates(
    monkeypatch,
    isolated_aqi_location_dependencies,
):
    backend_location, _ = isolated_aqi_location_dependencies
    backend_location.return_value = backend_sample(
        latitude=31.2305,
        longitude=121.4738,
        source="configured",
    )
    upstream = Mock(return_value=successful_response(42))
    monkeypatch.setattr(server.requests, "get", upstream)

    payload = run_aqi(
        lat=31.2304,
        lon=121.4737,
        accuracy=25.0,
        timestamp_ms=current_timestamp_ms(),
    )

    assert payload["status"] == "ok"
    assert payload["lat"] == 31.2305
    assert payload["lon"] == 121.4738
    requested_url = upstream.call_args.args[0]
    assert "latitude=31.2305" in requested_url
    assert "longitude=121.4738" in requested_url
    assert "latitude=31.2304" not in requested_url
    assert "longitude=121.4737" not in requested_url


@pytest.mark.parametrize(
    "backend_overrides",
    [
        {"captured_at": datetime.now(timezone.utc) - timedelta(seconds=31)},
        {"latitude": 32.2304, "longitude": 122.4737},
    ],
)
def test_mismatched_browser_and_backend_fail_closed(
    backend_overrides,
    isolated_aqi_location_dependencies,
):
    backend_location, upstream = isolated_aqi_location_dependencies
    backend_location.return_value = backend_sample(**backend_overrides)

    payload = run_aqi(
        lat=31.2304,
        lon=121.4737,
        accuracy=25.0,
        timestamp_ms=current_timestamp_ms(),
    )

    assert_location_unavailable(payload)
    upstream.assert_not_called()


@pytest.mark.parametrize("upstream_failure", ["timeout", "not_ok", "no_aqi"])
def test_upstream_failures_preserve_unavailable_contract_for_trusted_location(
    upstream_failure,
    monkeypatch,
    isolated_aqi_location_dependencies,
    capsys,
):
    backend_location, _ = isolated_aqi_location_dependencies
    backend_location.return_value = backend_sample()
    if upstream_failure == "timeout":
        upstream = Mock(
            side_effect=TimeoutError(
                "request to latitude=39.9042&longitude=116.4074 timed out"
            )
        )
    elif upstream_failure == "not_ok":
        upstream = Mock(
            return_value=SimpleNamespace(ok=False, status_code=503)
        )
    else:
        upstream = Mock(
            return_value=SimpleNamespace(
                ok=True,
                status_code=200,
                json=lambda: {"current": {}},
            )
        )
    monkeypatch.setattr(server.requests, "get", upstream)

    payload = run_aqi()

    assert UNAVAILABLE_KEYS <= payload.keys()
    assert payload["aqi"] is None
    assert payload["city"] == "Current Location"
    assert payload["level"] == "Unavailable"
    assert payload["color"] == "#b2bec3"
    assert payload["status"] == "unavailable"
    assert payload["lat"] == 39.9042
    assert payload["lon"] == 116.4074
    assert "error" in payload
    upstream.assert_called_once()
    output = capsys.readouterr().out
    assert "39.9042" not in output
    assert "116.4074" not in output


def test_aqi_endpoint_source_contains_no_shanghai_fallback():
    source = inspect.getsource(server.get_aqi_stats)

    for forbidden in (
        "SJTU",
        "Shanghai Jiao Tong",
        "31.025",
        "121.433",
    ):
        assert forbidden not in source


def test_server_disables_access_logs_that_would_expose_aqi_coordinates(
    monkeypatch,
):
    uvicorn_run = Mock()
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(run=uvicorn_run),
    )

    server.main()

    uvicorn_run.assert_called_once()
    assert uvicorn_run.call_args.kwargs["access_log"] is False

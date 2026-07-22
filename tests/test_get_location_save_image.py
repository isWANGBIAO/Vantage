import asyncio
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.manager import get_location
from src.services.location_trust import (
    LocationPurpose,
    LocationSample,
    LocationTrustResolver,
)


class NamedPositionSource:
    def __init__(self, name):
        self.name = name


def fake_position(**coordinate_overrides):
    values = {
        "latitude": 31.2304,
        "longitude": 121.4737,
        "accuracy": 25.0,
        "timestamp": datetime.now(timezone.utc),
        "position_source": NamedPositionSource("WI_FI"),
        "position_source_timestamp": datetime.now(timezone.utc),
        "is_remote_source": False,
    }
    values.update(coordinate_overrides)
    return SimpleNamespace(coordinate=SimpleNamespace(**values))


def install_fake_geolocator(monkeypatch, position):
    class FakeGeolocator:
        async def get_geoposition_async(self):
            return position

    monkeypatch.setattr(get_location, "Geolocator", FakeGeolocator)


def clear_static_location(monkeypatch):
    monkeypatch.delenv("VANTAGE_STATIC_LATITUDE", raising=False)
    monkeypatch.delenv("VANTAGE_STATIC_LONGITUDE", raising=False)


def test_save_image_with_gps_skips_exif_when_location_missing(monkeypatch, tmp_path):
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    photo_path = tmp_path / "photo.jpg"

    def fail_dump(*args, **kwargs):
        raise AssertionError("piexif.dump should not be called when location is missing")

    def fail_insert(*args, **kwargs):
        raise AssertionError("piexif.insert should not be called when location is missing")

    monkeypatch.setattr(get_location.piexif, "dump", fail_dump)
    monkeypatch.setattr(get_location.piexif, "insert", fail_insert)

    get_location.save_image_with_gps(str(photo_path), frame, None, None)

    assert photo_path.is_file()


def test_save_image_with_gps_supports_unicode_windows_paths(tmp_path):
    frame = np.full((8, 8, 3), 127, dtype=np.uint8)
    photo_path = tmp_path / "本机照片" / "照片.jpg"
    photo_path.parent.mkdir(parents=True)

    get_location.save_image_with_gps(str(photo_path), frame, None, None)

    assert photo_path.is_file()
    decoded = cv2.imdecode(np.fromfile(photo_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape == frame.shape


def test_get_location_returns_empty_coordinates_without_platform_geolocator(monkeypatch):
    clear_static_location(monkeypatch)
    monkeypatch.setattr(get_location, "Geolocator", None)

    assert get_location.get_trusted_location(resolver=LocationTrustResolver()) == (
        None,
        None,
    )


def test_get_location_uses_configured_static_coordinates(monkeypatch):
    monkeypatch.setenv("VANTAGE_STATIC_LATITUDE", "12.5")
    monkeypatch.setenv("VANTAGE_STATIC_LONGITUDE", "34.75")
    monkeypatch.setattr(get_location, "Geolocator", None)

    resolver = LocationTrustResolver()

    assert get_location.get_trusted_location(resolver=resolver) == (12.5, 34.75)


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        ("", ""),
        ("   ", "\t"),
    ],
)
def test_blank_static_coordinates_are_unconfigured_and_use_winrt(
    monkeypatch, latitude, longitude
):
    monkeypatch.setenv("VANTAGE_STATIC_LATITUDE", latitude)
    monkeypatch.setenv("VANTAGE_STATIC_LONGITUDE", longitude)
    install_fake_geolocator(monkeypatch, fake_position())

    assert get_location.get_trusted_location(
        resolver=LocationTrustResolver()
    ) == (31.2304, 121.4737)


@pytest.mark.parametrize(
    ("configured_name", "configured_value", "other_name", "other_value"),
    [
        ("VANTAGE_STATIC_LATITUDE", "12.5", "VANTAGE_STATIC_LONGITUDE", ""),
        ("VANTAGE_STATIC_LONGITUDE", "34.75", "VANTAGE_STATIC_LATITUDE", "   "),
        ("VANTAGE_STATIC_LATITUDE", "12.5", "VANTAGE_STATIC_LONGITUDE", None),
        ("VANTAGE_STATIC_LONGITUDE", "34.75", "VANTAGE_STATIC_LATITUDE", None),
    ],
)
def test_partial_static_configuration_fails_closed_without_winrt_fallback(
    monkeypatch, configured_name, configured_value, other_name, other_value
):
    monkeypatch.setenv(configured_name, configured_value)
    if other_value is None:
        monkeypatch.delenv(other_name, raising=False)
    else:
        monkeypatch.setenv(other_name, other_value)

    class UnexpectedGeolocator:
        def __init__(self):
            raise AssertionError("partial static configuration must not fall back")

    monkeypatch.setattr(get_location, "Geolocator", UnexpectedGeolocator)

    assert get_location.get_trusted_location(
        resolver=LocationTrustResolver()
    ) == (None, None)


def test_invalid_static_configuration_fails_closed_without_winrt_fallback(monkeypatch):
    monkeypatch.setenv("VANTAGE_STATIC_LATITUDE", "not-a-number")
    monkeypatch.setenv("VANTAGE_STATIC_LONGITUDE", "34.75")

    class UnexpectedGeolocator:
        def __init__(self):
            raise AssertionError("invalid static configuration must not fall back")

    monkeypatch.setattr(get_location, "Geolocator", UnexpectedGeolocator)

    assert get_location.get_trusted_location(
        resolver=LocationTrustResolver()
    ) == (None, None)


def test_fresh_local_wifi_position_is_trusted_for_exif(monkeypatch, capsys):
    clear_static_location(monkeypatch)
    install_fake_geolocator(monkeypatch, fake_position(accuracy=100.0))

    coordinates = get_location.get_trusted_location(
        purpose=LocationPurpose.EXIF,
        resolver=LocationTrustResolver(),
    )

    assert coordinates == (31.2304, 121.4737)
    output = capsys.readouterr().out
    assert "source=wi_fi" in output
    assert "accuracy=100.0" in output
    assert "status=trusted" in output
    assert "31.2304" not in output
    assert "121.4737" not in output


def test_default_position_source_is_rejected_even_with_small_accuracy(monkeypatch):
    clear_static_location(monkeypatch)
    position = fake_position(
        accuracy=0.1,
        position_source=NamedPositionSource("DEFAULT"),
    )
    install_fake_geolocator(monkeypatch, position)

    assert get_location.get_trusted_location(
        resolver=LocationTrustResolver()
    ) == (None, None)


@pytest.mark.parametrize(
    "coordinate_overrides",
    [
        {"is_remote_source": True},
        {"timestamp": datetime.now(timezone.utc) - timedelta(seconds=61)},
    ],
)
def test_remote_and_stale_positions_are_rejected(monkeypatch, coordinate_overrides):
    clear_static_location(monkeypatch)
    install_fake_geolocator(monkeypatch, fake_position(**coordinate_overrides))

    assert get_location.get_trusted_location(
        resolver=LocationTrustResolver()
    ) == (None, None)


def test_coordinate_timestamp_not_position_source_timestamp_controls_freshness(
    monkeypatch,
):
    clear_static_location(monkeypatch)
    now = datetime.now(timezone.utc)
    position = fake_position(
        timestamp=now - timedelta(seconds=61),
        position_source_timestamp=now,
    )
    install_fake_geolocator(monkeypatch, position)

    assert get_location.get_trusted_location(
        resolver=LocationTrustResolver()
    ) == (None, None)


@pytest.mark.parametrize(
    "missing_attribute",
    ["accuracy", "timestamp", "position_source", "is_remote_source"],
)
def test_incomplete_winrt_metadata_fails_closed(monkeypatch, missing_attribute):
    clear_static_location(monkeypatch)
    position = fake_position()
    delattr(position.coordinate, missing_attribute)
    install_fake_geolocator(monkeypatch, position)

    assert get_location.get_trusted_location(
        resolver=LocationTrustResolver()
    ) == (None, None)


@pytest.mark.parametrize(
    ("position_source", "expected"),
    [
        (NamedPositionSource("CELLULAR"), "cellular"),
        (NamedPositionSource("SATELLITE"), "satellite"),
        (NamedPositionSource("WI_FI"), "wi_fi"),
        (NamedPositionSource("IP_ADDRESS"), "ip_address"),
        (NamedPositionSource("UNKNOWN"), "unknown"),
        (NamedPositionSource("DEFAULT"), "default"),
        (NamedPositionSource("OBFUSCATED"), "obfuscated"),
        (0, "cellular"),
        (1, "satellite"),
        (2, "wi_fi"),
        (3, "ip_address"),
        (4, "unknown"),
        (5, "default"),
        (6, "obfuscated"),
    ],
)
def test_winrt_position_source_mapping_supports_names_and_numeric_enums(
    position_source, expected
):
    sample = get_location._winrt_coordinate_to_location_sample(
        fake_position(position_source=position_source).coordinate
    )

    assert sample is not None
    assert sample.source == expected


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        ("nan", "34.75"),
        ("inf", "34.75"),
        ("91", "34.75"),
        ("12.5", "181"),
    ],
)
def test_invalid_configured_static_coordinates_are_rejected(
    monkeypatch, latitude, longitude
):
    monkeypatch.setenv("VANTAGE_STATIC_LATITUDE", latitude)
    monkeypatch.setenv("VANTAGE_STATIC_LONGITUDE", longitude)
    monkeypatch.setattr(get_location, "Geolocator", None)

    assert get_location.get_trusted_location(
        resolver=LocationTrustResolver()
    ) == (None, None)


def test_get_location_remains_an_exif_wrapper(monkeypatch):
    calls = []

    def fake_get_trusted_location(purpose=LocationPurpose.EXIF, resolver=None):
        calls.append((purpose, resolver))
        return 12.5, 34.75

    monkeypatch.setattr(get_location, "get_trusted_location", fake_get_trusted_location)

    assert get_location.get_location() == (12.5, 34.75)
    assert calls == [(LocationPurpose.EXIF, None)]


def test_get_trusted_location_async_works_inside_running_asyncio_loop(monkeypatch):
    clear_static_location(monkeypatch)
    install_fake_geolocator(monkeypatch, fake_position())

    async def call_async_api_from_loop():
        return await get_location.get_trusted_location_async(
            resolver=LocationTrustResolver()
        )

    assert asyncio.run(call_async_api_from_loop()) == (31.2304, 121.4737)


def test_get_trusted_location_sample_async_preserves_winrt_metadata(monkeypatch):
    clear_static_location(monkeypatch)
    captured_at = datetime.now(timezone.utc)
    install_fake_geolocator(
        monkeypatch,
        fake_position(
            accuracy=25.0,
            timestamp=captured_at,
            position_source=NamedPositionSource("WI_FI"),
        ),
    )

    location_sample = asyncio.run(
        get_location.get_trusted_location_sample_async(
            purpose=LocationPurpose.AQI,
            resolver=LocationTrustResolver(),
        )
    )

    assert location_sample == LocationSample(
        latitude=31.2304,
        longitude=121.4737,
        accuracy_m=25.0,
        captured_at=captured_at,
        source="wi_fi",
        is_remote_source=False,
    )


def test_get_trusted_location_sample_async_returns_configured_metadata(monkeypatch):
    monkeypatch.setenv("VANTAGE_STATIC_LATITUDE", "12.5")
    monkeypatch.setenv("VANTAGE_STATIC_LONGITUDE", "34.75")
    monkeypatch.setattr(get_location, "Geolocator", None)

    location_sample = asyncio.run(
        get_location.get_trusted_location_sample_async(
            purpose=LocationPurpose.AQI,
            resolver=LocationTrustResolver(),
        )
    )

    assert location_sample is not None
    assert location_sample.latitude == 12.5
    assert location_sample.longitude == 34.75
    assert location_sample.accuracy_m == get_location.CONFIGURED_STATIC_ACCURACY_M
    assert location_sample.source == "configured"


def test_async_winrt_timeout_does_not_block_event_loop(monkeypatch, capsys):
    clear_static_location(monkeypatch)
    assert get_location.WINRT_LOCATION_TIMEOUT_SECONDS == 10
    monkeypatch.setattr(get_location, "WINRT_LOCATION_TIMEOUT_SECONDS", 0.01)

    async def exercise_timeout():
        operation_started = asyncio.Event()
        event_loop_progressed = asyncio.Event()

        class HangingGeolocator:
            async def get_geoposition_async(self):
                operation_started.set()
                await asyncio.Event().wait()

        monkeypatch.setattr(get_location, "Geolocator", HangingGeolocator)
        location_task = asyncio.create_task(
            get_location.get_trusted_location_async(
                resolver=LocationTrustResolver()
            )
        )
        await asyncio.wait_for(operation_started.wait(), timeout=0.1)
        asyncio.get_running_loop().call_soon(event_loop_progressed.set)
        await asyncio.wait_for(event_loop_progressed.wait(), timeout=0.1)
        return await asyncio.wait_for(location_task, timeout=0.2)

    assert asyncio.run(exercise_timeout()) == (None, None)
    output = capsys.readouterr().out
    assert "status=unknown" in output
    assert "reason=timeout" in output


def test_async_winrt_metadata_error_degrades_without_exposing_details(
    monkeypatch, capsys
):
    clear_static_location(monkeypatch)

    class PositionWithBrokenCoordinate:
        @property
        def coordinate(self):
            raise RuntimeError("secret coordinates 31.2304, 121.4737")

    install_fake_geolocator(monkeypatch, PositionWithBrokenCoordinate())

    async def read_broken_position():
        return await get_location.get_trusted_location_async(
            resolver=LocationTrustResolver()
        )

    assert asyncio.run(read_broken_position()) == (None, None)
    output = capsys.readouterr().out
    assert "status=unknown" in output
    assert "reason=api_error" in output
    assert "31.2304" not in output
    assert "121.4737" not in output


def test_sync_location_call_inside_event_loop_fails_closed_without_blocking(
    monkeypatch, capsys
):
    clear_static_location(monkeypatch)

    class SlowGeolocator:
        async def get_geoposition_async(self):
            await asyncio.sleep(0.2)
            return fake_position()

    monkeypatch.setattr(get_location, "Geolocator", SlowGeolocator)

    async def misuse_sync_api():
        started_at = time.monotonic()
        result = get_location.get_trusted_location(resolver=LocationTrustResolver())
        return result, time.monotonic() - started_at

    result, elapsed_seconds = asyncio.run(misuse_sync_api())

    assert result == (None, None)
    assert elapsed_seconds < 0.1
    output = capsys.readouterr().out
    assert "status=unknown" in output
    assert "reason=sync_called_in_event_loop" in output


def test_winrt_api_failure_returns_unknown_without_logging_exception_details(
    monkeypatch, capsys
):
    clear_static_location(monkeypatch)

    class BrokenGeolocator:
        async def get_geoposition_async(self):
            raise RuntimeError("secret coordinates 31.2304, 121.4737")

    monkeypatch.setattr(get_location, "Geolocator", BrokenGeolocator)

    assert get_location.get_trusted_location(
        resolver=LocationTrustResolver()
    ) == (None, None)
    output = capsys.readouterr().out
    assert "status=unknown" in output
    assert "reason=api_error" in output
    assert "31.2304" not in output
    assert "121.4737" not in output

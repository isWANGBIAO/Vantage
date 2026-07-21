from datetime import datetime, timedelta, timezone

import pytest

from src.services.location_trust import (
    LocationPurpose,
    LocationSample,
    LocationStatus,
    LocationTrustResolver,
)


NOW = datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc)


def sample(**overrides):
    values = {
        "latitude": 31.2304,
        "longitude": 121.4737,
        "accuracy_m": 10.0,
        "captured_at": NOW,
        "source": "satellite",
    }
    values.update(overrides)
    return LocationSample(**values)


@pytest.mark.parametrize("source", ["default", "ip_address", "unknown", "obfuscated"])
def test_default_and_ip_sources_are_rejected_even_with_small_accuracy(source):
    resolver = LocationTrustResolver()

    decision = resolver.resolve(
        sample(source=source, accuracy_m=0.1), LocationPurpose.AQI, now=NOW
    )

    assert decision.status is LocationStatus.UNKNOWN
    assert decision.sample is None


@pytest.mark.parametrize(
    ("source", "purpose", "accuracy_m"),
    [
        ("satellite", LocationPurpose.AQI, 5_000.0),
        ("satellite", LocationPurpose.EXIF, 100.0),
        ("wi_fi", LocationPurpose.AQI, 5_000.0),
        ("wi_fi", LocationPurpose.EXIF, 100.0),
        ("configured", LocationPurpose.AQI, 5_000.0),
        ("configured", LocationPurpose.EXIF, 100.0),
    ],
)
def test_satellite_and_wifi_samples_are_trusted_for_aqi_and_exif(
    source, purpose, accuracy_m
):
    resolver = LocationTrustResolver()
    location_sample = sample(source=source, accuracy_m=accuracy_m)

    decision = resolver.resolve(location_sample, purpose, now=NOW)

    assert decision.status is LocationStatus.TRUSTED
    assert decision.sample is location_sample


def test_cellular_is_only_trusted_for_aqi():
    location_sample = sample(source="cellular", accuracy_m=5_000.0)

    aqi_decision = LocationTrustResolver().resolve(
        location_sample, LocationPurpose.AQI, now=NOW
    )
    exif_decision = LocationTrustResolver().resolve(
        location_sample, LocationPurpose.EXIF, now=NOW
    )

    assert aqi_decision.status is LocationStatus.TRUSTED
    assert aqi_decision.sample is location_sample
    assert exif_decision.status is LocationStatus.UNKNOWN
    assert exif_decision.sample is None


def test_browser_is_only_trusted_for_high_accuracy_aqi():
    accepted = sample(source="browser", accuracy_m=1_000.0)
    rejected = sample(source="browser", accuracy_m=1_000.1)

    accepted_decision = LocationTrustResolver().resolve(
        accepted, LocationPurpose.AQI, now=NOW
    )
    rejected_decision = LocationTrustResolver().resolve(
        rejected, LocationPurpose.AQI, now=NOW
    )
    exif_decision = LocationTrustResolver().resolve(
        sample(source="browser", accuracy_m=1.0), LocationPurpose.EXIF, now=NOW
    )

    assert accepted_decision.status is LocationStatus.TRUSTED
    assert accepted_decision.sample is accepted
    assert rejected_decision.status is LocationStatus.UNKNOWN
    assert rejected_decision.sample is None
    assert exif_decision.status is LocationStatus.UNKNOWN
    assert exif_decision.sample is None


def test_exif_requires_100_meter_accuracy():
    accepted = sample(accuracy_m=100.0)
    rejected = sample(accuracy_m=100.1)

    accepted_decision = LocationTrustResolver().resolve(
        accepted, LocationPurpose.EXIF, now=NOW
    )
    rejected_decision = LocationTrustResolver().resolve(
        rejected, LocationPurpose.EXIF, now=NOW
    )

    assert accepted_decision.status is LocationStatus.TRUSTED
    assert accepted_decision.sample is accepted
    assert rejected_decision.status is LocationStatus.UNKNOWN
    assert rejected_decision.sample is None


def test_aqi_and_exif_use_purpose_specific_maximum_ages():
    sixty_seconds_old = sample(captured_at=NOW - timedelta(seconds=60))
    sixty_one_seconds_old = sample(captured_at=NOW - timedelta(seconds=61))
    one_hundred_twenty_seconds_old = sample(
        captured_at=NOW - timedelta(seconds=120)
    )

    assert (
        LocationTrustResolver()
        .resolve(sixty_seconds_old, LocationPurpose.EXIF, now=NOW)
        .status
        is LocationStatus.TRUSTED
    )
    assert (
        LocationTrustResolver()
        .resolve(sixty_one_seconds_old, LocationPurpose.EXIF, now=NOW)
        .status
        is LocationStatus.UNKNOWN
    )
    assert (
        LocationTrustResolver()
        .resolve(one_hundred_twenty_seconds_old, LocationPurpose.AQI, now=NOW)
        .status
        is LocationStatus.TRUSTED
    )


@pytest.mark.parametrize(
    "location_sample",
    [
        sample(latitude=float("nan")),
        sample(longitude=float("inf")),
        sample(latitude=90.1),
        sample(longitude=-180.1),
        sample(accuracy_m=0.0),
        sample(accuracy_m=-1.0),
        sample(accuracy_m=float("nan")),
        sample(is_remote_source=True),
        sample(captured_at=NOW - timedelta(seconds=121)),
        sample(captured_at=NOW + timedelta(seconds=31)),
        sample(captured_at=NOW.replace(tzinfo=None)),
    ],
)
def test_invalid_remote_stale_and_future_samples_are_unknown(location_sample):
    resolver = LocationTrustResolver()

    decision = resolver.resolve(location_sample, LocationPurpose.AQI, now=NOW)

    assert decision.status is LocationStatus.UNKNOWN
    assert decision.sample is None


def test_implausible_short_interval_jump_is_rejected():
    resolver = LocationTrustResolver()
    baseline = sample(latitude=31.2304, longitude=121.4737)
    jumped_at = NOW + timedelta(seconds=60)
    cross_city = sample(
        latitude=39.9042,
        longitude=116.4074,
        captured_at=jumped_at,
    )

    assert (
        resolver.resolve(baseline, LocationPurpose.AQI, now=NOW).status
        is LocationStatus.TRUSTED
    )
    decision = resolver.resolve(cross_city, LocationPurpose.AQI, now=jumped_at)

    assert decision.status is LocationStatus.UNKNOWN
    assert decision.sample is None


def test_continuity_uses_150_meters_per_second_limit():
    resolver = LocationTrustResolver()
    baseline = sample(latitude=0.0, longitude=0.0, accuracy_m=1.0)
    next_time = NOW + timedelta(seconds=1)
    too_fast = sample(
        latitude=0.0,
        longitude=0.0018,
        accuracy_m=1.0,
        captured_at=next_time,
    )

    assert (
        resolver.resolve(baseline, LocationPurpose.AQI, now=NOW).status
        is LocationStatus.TRUSTED
    )
    decision = resolver.resolve(too_fast, LocationPurpose.AQI, now=next_time)

    assert decision.status is LocationStatus.UNKNOWN
    assert decision.sample is None


def test_continuity_subtracts_both_accuracy_radii_from_distance():
    resolver = LocationTrustResolver()
    baseline = sample(latitude=0.0, longitude=0.0, accuracy_m=200.0)
    next_time = NOW + timedelta(seconds=1)
    uncertain_fix = sample(
        latitude=0.0,
        longitude=0.0045,
        accuracy_m=200.0,
        captured_at=next_time,
    )

    assert (
        resolver.resolve(baseline, LocationPurpose.AQI, now=NOW).status
        is LocationStatus.TRUSTED
    )
    decision = resolver.resolve(uncertain_fix, LocationPurpose.AQI, now=next_time)

    assert decision.status is LocationStatus.TRUSTED
    assert decision.sample is uncertain_fix


@pytest.mark.parametrize("seconds_delta", [0, -1])
def test_continuity_rejects_non_increasing_capture_times(seconds_delta):
    resolver = LocationTrustResolver()
    baseline = sample()
    non_increasing = sample(captured_at=NOW + timedelta(seconds=seconds_delta))

    assert (
        resolver.resolve(baseline, LocationPurpose.AQI, now=NOW).status
        is LocationStatus.TRUSTED
    )
    decision = resolver.resolve(non_increasing, LocationPurpose.AQI, now=NOW)

    assert decision.status is LocationStatus.UNKNOWN
    assert decision.sample is None


def test_long_gap_allows_a_new_trusted_baseline():
    resolver = LocationTrustResolver()
    baseline = sample(latitude=31.2304, longitude=121.4737)
    new_time = NOW + timedelta(seconds=301)
    new_baseline = sample(
        latitude=39.9042,
        longitude=116.4074,
        captured_at=new_time,
    )

    assert (
        resolver.resolve(baseline, LocationPurpose.EXIF, now=NOW).status
        is LocationStatus.TRUSTED
    )
    decision = resolver.resolve(new_baseline, LocationPurpose.EXIF, now=new_time)

    assert decision.status is LocationStatus.TRUSTED
    assert decision.sample is new_baseline

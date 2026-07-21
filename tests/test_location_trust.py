import math
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from src.services import location_trust
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


@pytest.mark.parametrize("source", ["configured", "satellite", "wi_fi"])
def test_aqi_metadata_rich_sources_accept_5000_meters_and_reject_more(source):
    accepted = sample(source=source, accuracy_m=5_000.0)
    rejected = sample(source=source, accuracy_m=5_000.1)

    accepted_decision = LocationTrustResolver().resolve(
        accepted, LocationPurpose.AQI, now=NOW
    )
    rejected_decision = LocationTrustResolver().resolve(
        rejected, LocationPurpose.AQI, now=NOW
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


def test_future_tolerance_accepts_30_seconds_and_rejects_more():
    at_tolerance = sample(captured_at=NOW + timedelta(seconds=30))
    beyond_tolerance = sample(captured_at=NOW + timedelta(seconds=30.1))

    accepted_decision = LocationTrustResolver().resolve(
        at_tolerance, LocationPurpose.AQI, now=NOW
    )
    rejected_decision = LocationTrustResolver().resolve(
        beyond_tolerance, LocationPurpose.AQI, now=NOW
    )

    assert accepted_decision.status is LocationStatus.TRUSTED
    assert accepted_decision.sample is at_tolerance
    assert rejected_decision.status is LocationStatus.UNKNOWN
    assert rejected_decision.sample is None


def test_future_tolerance_sample_does_not_poison_continuity_baseline():
    resolver = LocationTrustResolver()
    future = sample(captured_at=NOW + timedelta(seconds=30))
    current = sample(
        latitude=39.9042,
        longitude=116.4074,
        captured_at=NOW,
    )

    future_decision = resolver.resolve(future, LocationPurpose.AQI, now=NOW)
    current_decision = resolver.resolve(current, LocationPurpose.AQI, now=NOW)

    assert future_decision.status is LocationStatus.TRUSTED
    assert current_decision.status is LocationStatus.TRUSTED
    assert current_decision.sample is current


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


def test_continuity_accepts_exact_speed_limit_and_rejects_slightly_more():
    def decision_for_effective_distance(effective_distance_m):
        resolver = LocationTrustResolver()
        baseline = sample(latitude=0.0, longitude=0.0, accuracy_m=1.0)
        next_time = NOW + timedelta(seconds=1)
        longitude = math.degrees((effective_distance_m + 2.0) / 6_371_000)
        moved = sample(
            latitude=0.0,
            longitude=longitude,
            accuracy_m=1.0,
            captured_at=next_time,
        )

        assert (
            resolver.resolve(baseline, LocationPurpose.AQI, now=NOW).status
            is LocationStatus.TRUSTED
        )
        return resolver.resolve(moved, LocationPurpose.AQI, now=next_time)

    at_limit = decision_for_effective_distance(150.0)
    above_limit = decision_for_effective_distance(150.1)

    assert at_limit.status is LocationStatus.TRUSTED
    assert at_limit.sample is not None
    assert above_limit.status is LocationStatus.UNKNOWN
    assert above_limit.sample is None


@pytest.mark.parametrize("seconds_delta", [0, -1])
def test_continuity_rejects_non_increasing_capture_times(seconds_delta):
    resolver = LocationTrustResolver()
    baseline = sample()
    non_increasing = sample(
        longitude=121.4738,
        captured_at=NOW + timedelta(seconds=seconds_delta),
    )

    assert (
        resolver.resolve(baseline, LocationPurpose.AQI, now=NOW).status
        is LocationStatus.TRUSTED
    )
    decision = resolver.resolve(non_increasing, LocationPurpose.AQI, now=NOW)

    assert decision.status is LocationStatus.UNKNOWN
    assert decision.sample is None


def test_same_sample_is_idempotently_trusted_for_aqi_then_exif():
    resolver = LocationTrustResolver()
    shared_sample = sample(accuracy_m=50.0)

    aqi_decision = resolver.resolve(shared_sample, LocationPurpose.AQI, now=NOW)
    exif_decision = resolver.resolve(shared_sample, LocationPurpose.EXIF, now=NOW)

    assert aqi_decision.status is LocationStatus.TRUSTED
    assert exif_decision.status is LocationStatus.TRUSTED
    assert exif_decision.sample is shared_sample


def test_concurrent_candidates_are_serialized_against_latest_baseline(monkeypatch):
    resolver = LocationTrustResolver()
    baseline = sample(latitude=0.0, longitude=0.0, accuracy_m=1.0)
    contender_time = NOW + timedelta(seconds=1)
    contenders = [
        sample(
            latitude=0.0,
            longitude=longitude,
            accuracy_m=1.0,
            captured_at=contender_time,
        )
        for longitude in (-0.001, 0.001)
    ]
    original_distance = location_trust._distance_m
    rendezvous = threading.Barrier(2)

    def synchronized_distance(first, second):
        if first is baseline:
            try:
                rendezvous.wait(timeout=1)
            except threading.BrokenBarrierError:
                pass
        return original_distance(first, second)

    monkeypatch.setattr(location_trust, "_distance_m", synchronized_distance)
    assert (
        resolver.resolve(baseline, LocationPurpose.AQI, now=NOW).status
        is LocationStatus.TRUSTED
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        decisions = list(
            executor.map(
                lambda contender: resolver.resolve(
                    contender, LocationPurpose.AQI, now=contender_time
                ),
                contenders,
            )
        )

    statuses = [decision.status for decision in decisions]
    assert statuses.count(LocationStatus.TRUSTED) == 1
    assert statuses.count(LocationStatus.UNKNOWN) == 1


def test_continuity_window_includes_exactly_300_seconds():
    resolver = LocationTrustResolver()
    baseline = sample(latitude=0.0, longitude=0.0, accuracy_m=1.0)
    at_window_end = NOW + timedelta(seconds=300)
    implausible = sample(
        latitude=0.0,
        longitude=1.0,
        accuracy_m=1.0,
        captured_at=at_window_end,
    )

    assert (
        resolver.resolve(baseline, LocationPurpose.AQI, now=NOW).status
        is LocationStatus.TRUSTED
    )
    decision = resolver.resolve(implausible, LocationPurpose.AQI, now=at_window_end)

    assert decision.status is LocationStatus.UNKNOWN
    assert decision.sample is None


def test_rejected_sample_does_not_replace_last_accepted_sample():
    resolver = LocationTrustResolver()
    baseline = sample(latitude=0.0, longitude=0.0, accuracy_m=1.0)
    rejected_time = NOW + timedelta(seconds=1)
    rejected_jump = sample(
        latitude=0.0,
        longitude=1.0,
        accuracy_m=1.0,
        captured_at=rejected_time,
    )
    followup_time = NOW + timedelta(seconds=300)
    plausible_from_baseline = sample(
        latitude=0.0,
        longitude=0.27,
        accuracy_m=1.0,
        captured_at=followup_time,
    )

    assert (
        resolver.resolve(baseline, LocationPurpose.AQI, now=NOW).status
        is LocationStatus.TRUSTED
    )
    assert (
        resolver.resolve(
            rejected_jump, LocationPurpose.AQI, now=rejected_time
        ).status
        is LocationStatus.UNKNOWN
    )
    decision = resolver.resolve(
        plausible_from_baseline, LocationPurpose.AQI, now=followup_time
    )

    assert decision.status is LocationStatus.TRUSTED
    assert decision.sample is plausible_from_baseline


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

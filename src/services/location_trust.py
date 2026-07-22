import math
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


AQI_MAX_SAMPLE_AGE_SECONDS = 120
EXIF_MAX_SAMPLE_AGE_SECONDS = 60
FUTURE_TOLERANCE_SECONDS = 30
CONTINUITY_WINDOW_SECONDS = 300
MAX_PLAUSIBLE_SPEED_M_S = 150
EXIF_MAX_ACCURACY_M = 100
AQI_METADATA_MAX_ACCURACY_M = 5_000
BROWSER_MAX_ACCURACY_M = 1_000
BROWSER_BACKEND_MAX_TIMESTAMP_SKEW_SECONDS = 30
BROWSER_BACKEND_MAX_EFFECTIVE_DISTANCE_M = 1_000


class LocationPurpose(str, Enum):
    AQI = "aqi"
    EXIF = "exif"


class LocationStatus(str, Enum):
    TRUSTED = "trusted"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LocationSample:
    latitude: float
    longitude: float
    accuracy_m: float
    captured_at: datetime
    source: str
    is_remote_source: bool = False


@dataclass(frozen=True)
class LocationDecision:
    status: LocationStatus
    sample: LocationSample | None
    reason: str


class LocationTrustResolver:
    def __init__(self) -> None:
        self._last_accepted_sample: LocationSample | None = None
        self._lock = threading.RLock()

    def resolve(
        self,
        sample: LocationSample,
        purpose: LocationPurpose,
        *,
        now: datetime | None = None,
    ) -> LocationDecision:
        with self._lock:
            return self._resolve_locked(sample, purpose, now=now)

    def _resolve_locked(
        self,
        sample: LocationSample,
        purpose: LocationPurpose,
        *,
        now: datetime | None,
    ) -> LocationDecision:
        if not _is_valid_sample(sample):
            return _unknown("invalid_sample")
        if not isinstance(sample.is_remote_source, bool):
            return _unknown("invalid_remote_metadata")
        if sample.is_remote_source:
            return _unknown("remote_source")

        current_time = _normalized_datetime(now or datetime.now(timezone.utc))
        captured_at = _normalized_datetime(sample.captured_at)
        if current_time is None or captured_at is None:
            return _unknown("invalid_timestamp")

        age_seconds = (current_time - captured_at).total_seconds()
        if age_seconds < -FUTURE_TOLERANCE_SECONDS:
            return _unknown("future_sample")
        maximum_age_seconds = _maximum_age_seconds(purpose)
        if maximum_age_seconds is None:
            return _unknown("unsupported_purpose")
        if age_seconds > maximum_age_seconds:
            return _unknown("stale_sample")

        accuracy_limit = _accuracy_limit(sample.source, purpose)
        if accuracy_limit is None:
            return _unknown("source_not_allowed")
        if sample.accuracy_m > accuracy_limit:
            return _unknown("insufficient_accuracy")

        continuity_rejection = self._continuity_rejection(sample)
        if continuity_rejection is not None:
            return _unknown(continuity_rejection)

        if age_seconds >= 0:
            self._last_accepted_sample = sample
        return LocationDecision(LocationStatus.TRUSTED, sample, "trusted")

    def _continuity_rejection(self, sample: LocationSample) -> str | None:
        previous = self._last_accepted_sample
        if previous is None:
            return None
        if sample == previous:
            return None

        elapsed_seconds = (sample.captured_at - previous.captured_at).total_seconds()
        if elapsed_seconds <= 0:
            return "non_increasing_timestamp"
        if elapsed_seconds > CONTINUITY_WINDOW_SECONDS:
            return None

        minimum_distance_m = max(
            0,
            _distance_m(previous, sample)
            - previous.accuracy_m
            - sample.accuracy_m,
        )
        if minimum_distance_m / elapsed_seconds > MAX_PLAUSIBLE_SPEED_M_S:
            return "implausible_movement"
        return None


def compare_browser_location(
    browser_sample: LocationSample,
    backend_sample: LocationSample,
    *,
    now: datetime | None = None,
) -> LocationDecision:
    """Use browser metadata only to corroborate an independently trusted sample."""
    if not _is_valid_sample(browser_sample):
        return _unknown("browser_invalid_sample")
    if not isinstance(browser_sample.is_remote_source, bool):
        return _unknown("browser_invalid_remote_metadata")
    if browser_sample.is_remote_source:
        return _unknown("browser_remote_source")
    if not isinstance(browser_sample.source, str) or (
        browser_sample.source.strip().lower() != "browser"
    ):
        return _unknown("browser_source_required")

    current_time = _normalized_datetime(now or datetime.now(timezone.utc))
    browser_captured_at = _normalized_datetime(browser_sample.captured_at)
    if current_time is None or browser_captured_at is None:
        return _unknown("browser_invalid_timestamp")
    browser_age_seconds = (current_time - browser_captured_at).total_seconds()
    if browser_age_seconds < -FUTURE_TOLERANCE_SECONDS:
        return _unknown("browser_future_sample")
    if browser_age_seconds > AQI_MAX_SAMPLE_AGE_SECONDS:
        return _unknown("browser_stale_sample")
    if browser_sample.accuracy_m > BROWSER_MAX_ACCURACY_M:
        return _unknown("browser_insufficient_accuracy")

    backend_decision = LocationTrustResolver().resolve(
        backend_sample,
        LocationPurpose.AQI,
        now=current_time,
    )
    if (
        backend_decision.status is not LocationStatus.TRUSTED
        or backend_decision.sample is None
    ):
        return _unknown("backend_source_not_allowed")

    backend_captured_at = _normalized_datetime(backend_sample.captured_at)
    if backend_captured_at is None:
        return _unknown("backend_invalid_timestamp")
    timestamp_skew_seconds = abs(
        (browser_captured_at - backend_captured_at).total_seconds()
    )
    if timestamp_skew_seconds > BROWSER_BACKEND_MAX_TIMESTAMP_SKEW_SECONDS:
        return _unknown("location_timestamp_mismatch")

    effective_distance_m = max(
        0,
        _distance_m(browser_sample, backend_sample)
        - browser_sample.accuracy_m
        - backend_sample.accuracy_m,
    )
    exceeds_distance_limit = (
        effective_distance_m > BROWSER_BACKEND_MAX_EFFECTIVE_DISTANCE_M
        and not math.isclose(
            effective_distance_m,
            BROWSER_BACKEND_MAX_EFFECTIVE_DISTANCE_M,
            abs_tol=1e-6,
        )
    )
    if exceeds_distance_limit:
        return _unknown("location_mismatch")
    return LocationDecision(LocationStatus.TRUSTED, backend_sample, "locations_match")


def _unknown(reason: str) -> LocationDecision:
    return LocationDecision(LocationStatus.UNKNOWN, None, reason)


def _is_valid_sample(sample: LocationSample) -> bool:
    coordinates_and_accuracy = (
        sample.latitude,
        sample.longitude,
        sample.accuracy_m,
    )
    if not all(_is_finite_number(value) for value in coordinates_and_accuracy):
        return False
    return (
        -90 <= sample.latitude <= 90
        and -180 <= sample.longitude <= 180
        and sample.accuracy_m > 0
    )


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _normalized_datetime(value: object) -> datetime | None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    if value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _accuracy_limit(source: object, purpose: LocationPurpose) -> float | None:
    if not isinstance(source, str) or not isinstance(purpose, LocationPurpose):
        return None

    normalized_source = source.strip().lower()
    if normalized_source == "cellular":
        return AQI_METADATA_MAX_ACCURACY_M if purpose is LocationPurpose.AQI else None
    if normalized_source in {"configured", "satellite", "wi_fi"}:
        if purpose is LocationPurpose.EXIF:
            return EXIF_MAX_ACCURACY_M
        if purpose is LocationPurpose.AQI:
            return AQI_METADATA_MAX_ACCURACY_M
    return None


def _maximum_age_seconds(purpose: LocationPurpose) -> int | None:
    if purpose is LocationPurpose.AQI:
        return AQI_MAX_SAMPLE_AGE_SECONDS
    if purpose is LocationPurpose.EXIF:
        return EXIF_MAX_SAMPLE_AGE_SECONDS
    return None


def _distance_m(first: LocationSample, second: LocationSample) -> float:
    first_latitude = math.radians(first.latitude)
    second_latitude = math.radians(second.latitude)
    latitude_delta = second_latitude - first_latitude
    longitude_delta = math.radians(second.longitude - first.longitude)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(first_latitude)
        * math.cos(second_latitude)
        * math.sin(longitude_delta / 2) ** 2
    )
    return 2 * 6_371_000 * math.asin(math.sqrt(haversine))

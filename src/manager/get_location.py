import asyncio
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import cv2
import piexif

from src.services.location_trust import (
    LocationPurpose,
    LocationSample,
    LocationStatus,
    LocationTrustResolver,
)

if sys.platform == "win32":
    try:
        from winsdk.windows.devices.geolocation import Geolocator
    except ImportError:
        Geolocator = None
else:
    Geolocator = None


# A static override is an explicit operator assertion, not a device accuracy claim.
# Use the EXIF acceptance ceiling so it remains opt-in but is never presented as
# more precise than the trust policy can justify.
CONFIGURED_STATIC_ACCURACY_M = 100.0

_POSITION_SOURCE_NAMES = {
    "CELLULAR": "cellular",
    "SATELLITE": "satellite",
    "WI_FI": "wi_fi",
    "IP_ADDRESS": "ip_address",
    "UNKNOWN": "unknown",
    "DEFAULT": "default",
    "OBFUSCATED": "obfuscated",
}
_POSITION_SOURCE_VALUES = {
    0: "cellular",
    1: "satellite",
    2: "wi_fi",
    3: "ip_address",
    4: "unknown",
    5: "default",
    6: "obfuscated",
}
_MISSING = object()
_SHARED_LOCATION_TRUST_RESOLVER = LocationTrustResolver()


def _timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log_location_result(source, accuracy, status, reason):
    displayed_accuracy = (
        accuracy
        if isinstance(accuracy, (int, float)) and not isinstance(accuracy, bool)
        else "unknown"
    )
    print(
        f"Time {_timestamp()} Location source={source} accuracy={displayed_accuracy} "
        f"status={status} reason={reason}"
    )


def _configured_static_location_sample():
    latitude = os.environ.get("VANTAGE_STATIC_LATITUDE")
    longitude = os.environ.get("VANTAGE_STATIC_LONGITUDE")
    is_configured = latitude is not None or longitude is not None
    if not is_configured:
        return False, None

    try:
        sample = LocationSample(
            latitude=float(latitude),
            longitude=float(longitude),
            accuracy_m=CONFIGURED_STATIC_ACCURACY_M,
            captured_at=datetime.now(timezone.utc),
            source="configured",
            is_remote_source=False,
        )
    except (TypeError, ValueError):
        return True, None
    return True, sample


def _winrt_position_source_name(position_source):
    source_name = getattr(position_source, "name", None)
    if isinstance(source_name, str):
        mapped_name = _POSITION_SOURCE_NAMES.get(source_name.strip().upper())
        if mapped_name is not None:
            return mapped_name

    if isinstance(position_source, int) and not isinstance(position_source, bool):
        return _POSITION_SOURCE_VALUES.get(int(position_source))
    return None


def _winrt_coordinate_to_location_sample(coordinate):
    required_attributes = (
        "latitude",
        "longitude",
        "accuracy",
        "timestamp",
        "position_source",
        "is_remote_source",
    )
    values = {
        attribute: getattr(coordinate, attribute, _MISSING)
        for attribute in required_attributes
    }
    if any(value is _MISSING for value in values.values()):
        return None

    source = _winrt_position_source_name(values["position_source"])
    is_remote_source = values["is_remote_source"]
    if source is None or not isinstance(is_remote_source, bool):
        return None

    return LocationSample(
        latitude=values["latitude"],
        longitude=values["longitude"],
        accuracy_m=values["accuracy"],
        captured_at=values["timestamp"],
        source=source,
        is_remote_source=is_remote_source,
    )


def _resolve_location_sample(sample, purpose, resolver):
    decision = resolver.resolve(sample, purpose)
    _log_location_result(
        sample.source,
        sample.accuracy_m,
        decision.status.value,
        decision.reason,
    )
    if decision.status is LocationStatus.TRUSTED and decision.sample is not None:
        return decision.sample.latitude, decision.sample.longitude
    return None, None


def get_trusted_location(
    purpose=LocationPurpose.EXIF,
    resolver=None,
):
    active_resolver = (
        resolver if resolver is not None else _SHARED_LOCATION_TRUST_RESOLVER
    )

    has_static_configuration, static_sample = _configured_static_location_sample()
    if has_static_configuration:
        if static_sample is None:
            _log_location_result(
                "configured",
                CONFIGURED_STATIC_ACCURACY_M,
                LocationStatus.UNKNOWN.value,
                "invalid_configuration",
            )
            return None, None
        return _resolve_location_sample(static_sample, purpose, active_resolver)

    if Geolocator is None:
        _log_location_result(
            "winrt",
            "unknown",
            LocationStatus.UNKNOWN.value,
            "service_unavailable",
        )
        return None, None

    async def fetch_location():
        try:
            locator = Geolocator()
            position = await locator.get_geoposition_async()
            coordinate = getattr(position, "coordinate", _MISSING)
            if coordinate is _MISSING:
                _log_location_result(
                    "winrt",
                    "unknown",
                    LocationStatus.UNKNOWN.value,
                    "incomplete_metadata",
                )
                return None, None
            sample = _winrt_coordinate_to_location_sample(coordinate)
            if sample is None:
                _log_location_result(
                    "winrt",
                    "unknown",
                    LocationStatus.UNKNOWN.value,
                    "incomplete_metadata",
                )
                return None, None
            return _resolve_location_sample(sample, purpose, active_resolver)
        except Exception:
            _log_location_result(
                "winrt",
                "unknown",
                LocationStatus.UNKNOWN.value,
                "api_error",
            )
            return None, None

    def run_async_in_thread(result_holder):
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result_holder["coordinates"] = loop.run_until_complete(fetch_location())
        except Exception:
            _log_location_result(
                "winrt",
                "unknown",
                LocationStatus.UNKNOWN.value,
                "api_error",
            )
            result_holder["coordinates"] = (None, None)
        finally:
            loop.close()

    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop is not None:
        result_holder = {}
        thread = threading.Thread(target=run_async_in_thread, args=(result_holder,))
        thread.start()
        thread.join()
        return result_holder.get("coordinates", (None, None))
    return asyncio.run(fetch_location())


def get_location():
    return get_trusted_location(LocationPurpose.EXIF)


def convert_to_exif_coords(value):
    degrees = int(value)
    minutes_float = abs((value - degrees) * 60)
    minutes = int(minutes_float)
    seconds = int((minutes_float - minutes) * 6000)
    return ((degrees, 1), (minutes, 1), (seconds, 100))


def save_image_with_gps(photo_path, frame, latitude, longitude):
    resolved_path = Path(photo_path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    extension = resolved_path.suffix or ".jpg"
    encoded, image_buffer = cv2.imencode(extension, frame)
    if not encoded:
        raise OSError(f"OpenCV could not encode image as {extension}")

    # cv2.imwrite() does not reliably support non-ASCII Windows paths.
    image_buffer.tofile(str(resolved_path))

    if latitude is None or longitude is None:
        print(f"Time {_timestamp()} Location unavailable; skipping GPS EXIF for {photo_path}")
        return

    gps_ifd = {
        piexif.GPSIFD.GPSLatitudeRef: "N" if latitude >= 0 else "S",
        piexif.GPSIFD.GPSLatitude: convert_to_exif_coords(abs(latitude)),
        piexif.GPSIFD.GPSLongitudeRef: "E" if longitude >= 0 else "W",
        piexif.GPSIFD.GPSLongitude: convert_to_exif_coords(abs(longitude)),
    }

    try:
        exif_dict = {"GPS": gps_ifd}
        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, str(resolved_path))
    except Exception as exc:
        print(f"Time {_timestamp()} Saved image but could not write GPS EXIF for {photo_path}: {exc}")

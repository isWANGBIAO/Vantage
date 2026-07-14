import cv2
import numpy as np

from src.manager import get_location


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
    monkeypatch.delenv("VANTAGE_STATIC_LATITUDE", raising=False)
    monkeypatch.delenv("VANTAGE_STATIC_LONGITUDE", raising=False)
    monkeypatch.setattr(get_location, "Geolocator", None)

    assert get_location.get_location() == (None, None)


def test_get_location_uses_configured_static_coordinates(monkeypatch):
    monkeypatch.setenv("VANTAGE_STATIC_LATITUDE", "12.5")
    monkeypatch.setenv("VANTAGE_STATIC_LONGITUDE", "34.75")
    monkeypatch.setattr(get_location, "Geolocator", None)

    assert get_location.get_location() == (12.5, 34.75)

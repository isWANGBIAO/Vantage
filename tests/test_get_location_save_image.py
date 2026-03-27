import numpy as np

from src.manager import get_location


def test_save_image_with_gps_skips_exif_when_location_missing(monkeypatch, tmp_path):
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    photo_path = tmp_path / "photo.jpg"
    imwrite_calls = []

    def fake_imwrite(path, image):
        imwrite_calls.append((path, image.shape))
        return True

    def fail_dump(*args, **kwargs):
        raise AssertionError("piexif.dump should not be called when location is missing")

    def fail_insert(*args, **kwargs):
        raise AssertionError("piexif.insert should not be called when location is missing")

    monkeypatch.setattr(get_location.cv2, "imwrite", fake_imwrite)
    monkeypatch.setattr(get_location.piexif, "dump", fail_dump)
    monkeypatch.setattr(get_location.piexif, "insert", fail_insert)

    get_location.save_image_with_gps(str(photo_path), frame, None, None)

    assert imwrite_calls == [(str(photo_path), frame.shape)]

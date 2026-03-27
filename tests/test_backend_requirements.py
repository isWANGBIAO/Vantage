from pathlib import Path


REQUIRED_BACKEND_PACKAGES = {
    "apscheduler",
    "cv2-enumerate-cameras",
    "fastapi",
    "mediapipe",
    "piexif",
    "python-multipart",
    "ultralytics",
    "uvicorn",
    "winsdk",
}


def _normalize_requirement_name(line):
    name = line.strip()
    if not name or name.startswith("#"):
        return None

    for separator in ("==", ">=", "<=", "~=", "!=", ">", "<"):
        if separator in name:
            name = name.split(separator, 1)[0]
            break

    return name.strip().lower()


def test_requirements_cover_backend_runtime_dependencies():
    content = Path("requirements.txt").read_text(encoding="utf-8").splitlines()
    package_names = {
        normalized
        for line in content
        if (normalized := _normalize_requirement_name(line)) is not None
    }

    missing = REQUIRED_BACKEND_PACKAGES - package_names
    if "onnxruntime" not in package_names and "onnxruntime-gpu" not in package_names:
        missing.add("onnxruntime or onnxruntime-gpu")
    assert not missing, f"requirements.txt missing backend runtime packages: {sorted(missing)}"

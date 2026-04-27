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

REQUIRED_GPU_RUNTIME_PACKAGES = {
    "apscheduler",
    "cv2-enumerate-cameras",
    "fastapi",
    "matplotlib",
    "mss",
    "numpy",
    "onnxruntime-gpu",
    "openai",
    "opencv-python",
    "openpyxl",
    "pandas",
    "piexif",
    "pillow",
    "psutil",
    "pyinstaller",
    "python-dotenv",
    "python-multipart",
    "requests",
    "scienceplots",
    "torch",
    "torchvision",
    "ultralytics",
    "uvicorn",
    "winsdk",
}

FORBIDDEN_GPU_RUNTIME_PACKAGES = {
    "cython",
    "ipykernel",
    "ipython",
    "jax",
    "jaxlib",
    "jedi",
    "jupyter-client",
    "jupyter-core",
    "jupyter-server",
    "jupyterlab-pygments",
    "nbclassic",
    "nbclient",
    "nbconvert",
    "nbformat",
    "notebook",
    "polars",
    "polars-runtime-32",
    "torchaudio",
}


def _normalize_requirement_name(line):
    name = line.strip()
    if not name or name.startswith("#") or name.startswith("--"):
        return None

    if ";" in name:
        name = name.split(";", 1)[0]
    if "[" in name:
        name = name.split("[", 1)[0]

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


def test_gpu_runtime_requirements_are_minimal_and_reproducible():
    content = Path("requirements-backend-runtime-gpu.txt").read_text(encoding="utf-8").splitlines()
    package_names = {
        normalized
        for line in content
        if (normalized := _normalize_requirement_name(line)) is not None
    }

    missing = REQUIRED_GPU_RUNTIME_PACKAGES - package_names
    forbidden = FORBIDDEN_GPU_RUNTIME_PACKAGES & package_names

    assert not missing, f"GPU runtime requirements missing packages: {sorted(missing)}"
    assert not forbidden, f"GPU runtime requirements include forbidden packages: {sorted(forbidden)}"
    assert any("download.pytorch.org/whl/cu" in line for line in content)

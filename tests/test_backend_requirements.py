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
    "lap",
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

REQUIRED_CI_PACKAGES = {
    "cv2-enumerate-cameras",
    "fastapi",
    "jieba",
    "matplotlib",
    "mss",
    "numpy",
    "openai",
    "opencv-python-headless",
    "openpyxl",
    "pandas",
    "piexif",
    "pillow",
    "psutil",
    "pytest",
    "python-dotenv",
    "python-multipart",
    "requests",
    "scienceplots",
    "uvicorn",
}

FORBIDDEN_CI_PACKAGES = {
    "lap",
    "mediapipe",
    "onnxruntime-gpu",
    "torch",
    "torchaudio",
    "torchvision",
    "ultralytics",
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


def _find_requirement_lines(path, package_name):
    prefix = package_name.lower()
    return [
        line.strip().lower()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip().lower().startswith(prefix)
    ]


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


def test_ci_requirements_cover_tests_without_gpu_runtime():
    content = Path("requirements-ci.txt").read_text(encoding="utf-8").splitlines()
    package_names = {
        normalized
        for line in content
        if (normalized := _normalize_requirement_name(line)) is not None
    }

    missing = REQUIRED_CI_PACKAGES - package_names
    forbidden = FORBIDDEN_CI_PACKAGES & package_names

    assert not missing, f"requirements-ci.txt missing packages: {sorted(missing)}"
    assert not forbidden, f"requirements-ci.txt includes heavyweight runtime packages: {sorted(forbidden)}"


def test_backend_runtime_requirements_keep_macos_opencv_headless():
    opencv_lines = _find_requirement_lines("requirements-backend-runtime-gpu.txt", "opencv-python")
    assert any("opencv-python==" in line and 'sys_platform == "win32"' in line for line in opencv_lines)
    assert any(
        "opencv-python-headless==" in line and 'sys_platform != "win32"' in line
        for line in opencv_lines
    )
    assert any(
        "opencv-python==4.11.0.86" in line
        and 'sys_platform == "win32"' in line
        and 'python_version < "3.13"' in line
        for line in opencv_lines
    )
    assert any(
        "opencv-python==4.12.0.88" in line
        and 'sys_platform == "win32"' in line
        and 'python_version >= "3.13"' in line
        for line in opencv_lines
    )

    ultralytics_lines = _find_requirement_lines("requirements-backend-runtime-gpu.txt", "ultralytics")
    assert ultralytics_lines == ['ultralytics==8.4.0; sys_platform == "win32"']


def test_backend_runtime_requirements_keep_torch_windows_only():
    for package_name in ("torch", "torchvision"):
        lines = _find_requirement_lines("requirements-backend-runtime-gpu.txt", package_name)
        assert lines, f"requirements-backend-runtime-gpu.txt missing {package_name}"
        assert all('sys_platform == "win32"' in line for line in lines)


def test_development_requirements_mark_windows_only_packages():
    for package_name in ("pywin32", "pywinpty", "torch", "torchaudio", "torchvision", "ultralytics", "wmi", "winsdk"):
        lines = _find_requirement_lines("requirements.txt", package_name)
        assert lines, f"requirements.txt missing {package_name}"
        assert all('sys_platform == "win32"' in line for line in lines)

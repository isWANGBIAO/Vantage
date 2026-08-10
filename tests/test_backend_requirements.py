from pathlib import Path


REQUIREMENTS_ROOT = Path.cwd().resolve()
ENVIRONMENT_REQUIREMENT_FILES = (
    Path("requirements.txt"),
    Path("requirements-ci.txt"),
    Path("requirements-backend-runtime-gpu.txt"),
)

EXPECTED_SHARED_CORE_LINES = {
    "APScheduler==3.11.3",
    "SciencePlots==2.2.2",
    "chinese-calendar==1.11.0",
    "cv2-enumerate-cameras==1.3.3",
    "fastapi==0.141.1",
    "matplotlib==3.11.1",
    "mss==10.2.0",
    'numpy==2.2.6; python_version < "3.12"',
    'numpy==2.5.1; python_version >= "3.12"',
    "openai==1.109.1",
    "opencv-contrib-python==4.14.0.94",
    "openpyxl==3.1.5",
    "pandas==2.3.3",
    "piexif==1.1.3",
    "pillow==10.4.0",
    "psutil==6.1.1",
    "pydantic==2.13.4",
    "pydantic_core==2.46.4",
    "python-dotenv==1.2.2",
    "python-multipart==0.0.32",
    "requests==2.34.2",
    "tqdm==4.70.0",
    "uvicorn==0.52.1",
    'winsdk==1.0.0b10; sys_platform == "win32"',
    "zhdate==0.1",
}

SHARED_CORE_PACKAGE_NAMES = {
    line.split(";", 1)[0].split("==", 1)[0].strip().lower()
    for line in EXPECTED_SHARED_CORE_LINES
}


REQUIRED_BACKEND_PACKAGES = {
    "apscheduler",
    "cv2-enumerate-cameras",
    "fastapi",
    "mediapipe",
    "piexif",
    "python-multipart",
    "scienceplots",
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
    "openai",
    "opencv-contrib-python",
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
    "opencv-contrib-python",
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
    "onnxruntime",
    "onnxruntime-gpu",
    "torch",
    "torchaudio",
    "torchvision",
    "ultralytics",
}

OPENCV_DISTRIBUTION_NAMES = {
    "opencv-contrib-python",
    "opencv-contrib-python-headless",
    "opencv-python",
    "opencv-python-headless",
}


def _normalize_requirement_name(line):
    name = line.strip()
    if not name or name.startswith("#") or name.startswith("-"):
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


def _parse_requirement_include(line):
    stripped = line.strip()
    if stripped.startswith("-r "):
        return stripped[3:].strip()
    if stripped.startswith("--requirement "):
        return stripped[len("--requirement ") :].strip()
    if stripped.startswith("--requirement="):
        return stripped.split("=", 1)[1].strip()
    return None


def _read_requirement_lines(path, *, _stack=()):
    resolved = Path(path).resolve()
    assert resolved.is_relative_to(REQUIREMENTS_ROOT), (
        f"requirement include escapes repository root: {resolved}"
    )
    assert resolved not in _stack, f"cyclic requirement include: {resolved}"
    assert resolved.is_file(), f"missing requirement file: {resolved}"

    lines = []
    stack = (*_stack, resolved)
    for raw_line in resolved.read_text(encoding="utf-8").splitlines():
        include = _parse_requirement_include(raw_line)
        if include is not None:
            include_path = (resolved.parent / include).resolve()
            lines.extend(_read_requirement_lines(include_path, _stack=stack))
            continue
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("--"):
            lines.append(stripped)
    return lines


def _direct_requirement_lines(path):
    return [
        line.strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if _normalize_requirement_name(line) is not None
    ]


def _direct_requirement_includes(path):
    return [
        include
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if (include := _parse_requirement_include(line)) is not None
    ]


def _requirement_package_names(path):
    return {
        normalized
        for line in _read_requirement_lines(path)
        if (normalized := _normalize_requirement_name(line)) is not None
    }


def _find_requirement_lines(path, package_name):
    prefix = package_name.lower()
    return [
        line.strip().lower()
        for line in _read_requirement_lines(path)
        if line.strip().lower().startswith(prefix)
    ]


def test_environment_requirements_include_one_shared_core_without_duplicate_pins():
    for path in ENVIRONMENT_REQUIREMENT_FILES:
        assert _direct_requirement_includes(path) == ["requirements-core.txt"]
        overlay_names = {
            normalized
            for line in _direct_requirement_lines(path)
            if (normalized := _normalize_requirement_name(line)) is not None
        }
        duplicated = SHARED_CORE_PACKAGE_NAMES & overlay_names
        assert not duplicated, f"{path} duplicates shared pins: {sorted(duplicated)}"

    assert {
        _normalize_requirement_name(line)
        for line in _direct_requirement_lines("requirements-ci.txt")
    } == {"jieba", "pytest"}
    assert {
        _normalize_requirement_name(line)
        for line in _direct_requirement_lines("requirements-backend-runtime-gpu.txt")
    } == {"lap", "pyinstaller"}


def test_shared_core_owns_one_exact_compatible_dependency_contract():
    actual = set(_direct_requirement_lines("requirements-core.txt"))

    assert actual == EXPECTED_SHARED_CORE_LINES
    assert len(actual) == len(_direct_requirement_lines("requirements-core.txt"))


def test_all_effective_environments_use_one_opencv_distribution():
    for path in ENVIRONMENT_REQUIREMENT_FILES:
        opencv_distributions = (
            _requirement_package_names(path) & OPENCV_DISTRIBUTION_NAMES
        )
        assert opencv_distributions == {"opencv-contrib-python"}, (
            f"{path} must use only the MediaPipe-compatible OpenCV distribution"
        )


def test_requirements_cover_backend_runtime_dependencies():
    package_names = _requirement_package_names("requirements.txt")

    missing = REQUIRED_BACKEND_PACKAGES - package_names
    assert not missing, f"requirements.txt missing backend runtime packages: {sorted(missing)}"

    removed_detector_packages = {
        "onnxruntime",
        "onnxruntime-gpu",
        "torchaudio",
        "torchvision",
        "ultralytics",
    }
    assert not (removed_detector_packages & package_names)


def test_gpu_runtime_requirements_are_minimal_and_reproducible():
    content = _read_requirement_lines("requirements-backend-runtime-gpu.txt")
    package_names = _requirement_package_names("requirements-backend-runtime-gpu.txt")

    missing = REQUIRED_GPU_RUNTIME_PACKAGES - package_names
    forbidden = FORBIDDEN_GPU_RUNTIME_PACKAGES & package_names

    assert not missing, f"GPU runtime requirements missing packages: {sorted(missing)}"
    assert not forbidden, f"GPU runtime requirements include forbidden packages: {sorted(forbidden)}"
    assert not any("download.pytorch.org/whl/cu" in line for line in content)


def test_ci_requirements_cover_tests_without_gpu_runtime():
    package_names = _requirement_package_names("requirements-ci.txt")

    missing = REQUIRED_CI_PACKAGES - package_names
    forbidden = FORBIDDEN_CI_PACKAGES & package_names

    assert not missing, f"requirements-ci.txt missing packages: {sorted(missing)}"
    assert not forbidden, f"requirements-ci.txt includes heavyweight runtime packages: {sorted(forbidden)}"


def test_ci_covers_packaging_python_and_current_python_without_incompatible_numpy():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    requirements = "\n".join(_read_requirement_lines("requirements-ci.txt"))

    assert 'python-version: ["3.11", "3.13"]' in workflow
    assert "python-version: ${{ matrix.python-version }}" in workflow
    assert 'numpy==2.2.6; python_version < "3.12"' in requirements
    assert 'numpy==2.5.1; python_version >= "3.12"' in requirements


def test_development_requirements_pin_compatible_pydantic_pair():
    expected = {
        "pydantic==2.13.4",
        "pydantic_core==2.46.4",
    }
    actual = [
        line.strip()
        for line in _read_requirement_lines("requirements.txt")
        if _normalize_requirement_name(line) in {"pydantic", "pydantic_core"}
    ]

    assert set(actual) == expected
    assert len(actual) == len(expected)


def test_development_requirements_split_scipy_by_python_version():
    expected = {
        'scipy==1.17.1; python_version < "3.12"',
        'scipy==1.18.0; python_version >= "3.12"',
    }
    actual = [
        line.strip()
        for line in Path("requirements.txt").read_text(encoding="utf-8").splitlines()
        if _normalize_requirement_name(line) == "scipy"
    ]

    assert set(actual) == expected
    assert len(actual) == len(expected)


def test_development_requirements_keep_resolvable_cuda_and_compatibility_pins():
    content = Path("requirements.txt").read_text(encoding="utf-8").splitlines()

    assert "--extra-index-url https://download.pytorch.org/whl/cu130" in content
    expected = {
        "ipykernel": {"ipykernel==6.29.5"},
        "mpmath": {"mpmath==1.3.0"},
        "webcolors": {"webcolors==25.10.0"},
    }
    for package_name, expected_lines in expected.items():
        actual = {
            line.strip()
            for line in content
            if _normalize_requirement_name(line) == package_name
        }
        assert actual == expected_lines


def test_readme_recommends_environment_python_version():
    environment = Path("environment.yml").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "python=3.11" in environment
    assert (
        "Python 3.11 recommended for local backend packaging; CI also validates "
        "Python 3.13."
    ) in readme
    assert "Python 3.12 recommended." not in readme


def test_shared_core_pins_single_cross_platform_opencv_distribution():
    opencv_lines = [
        line
        for line in _read_requirement_lines("requirements-core.txt")
        if _normalize_requirement_name(line) in OPENCV_DISTRIBUTION_NAMES
    ]

    assert opencv_lines == ["opencv-contrib-python==4.14.0.94"]

    for package_name in ("onnxruntime", "onnxruntime-gpu", "torch", "torchvision", "ultralytics"):
        assert not _find_requirement_lines("requirements-backend-runtime-gpu.txt", package_name)


def test_development_requirements_mark_windows_only_packages():
    for package_name in ("pywin32", "pywinpty", "torch", "wmi", "winsdk"):
        lines = _find_requirement_lines("requirements.txt", package_name)
        assert lines, f"requirements.txt missing {package_name}"
        assert all('sys_platform == "win32"' in line for line in lines)

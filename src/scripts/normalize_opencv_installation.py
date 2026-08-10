from __future__ import annotations

import argparse
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
import re
import subprocess
import sys


OPENCV_DISTRIBUTIONS = (
    "opencv-contrib-python",
    "opencv-contrib-python-headless",
    "opencv-python",
    "opencv-python-headless",
)
TARGET_DISTRIBUTION = "opencv-contrib-python"
CV2_VERSION_PROBE = "import cv2; print(cv2.__version__)"


@dataclass(frozen=True)
class OpenCvTarget:
    distribution: str
    wheel_version: str
    cv2_version: str


def _canonicalize_distribution_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def read_target_contract(requirements_core_path):
    requirements_core_path = Path(requirements_core_path)
    targets = []
    for raw_line in requirements_core_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        match = re.fullmatch(
            r"([A-Za-z0-9_.-]+)\s*==\s*([^\s;]+)(?:\s*;.*)?",
            line,
        )
        if match is None:
            continue
        distribution = _canonicalize_distribution_name(match.group(1))
        if distribution in OPENCV_DISTRIBUTIONS:
            targets.append((distribution, match.group(2)))

    if len(targets) != 1:
        raise ValueError(
            "requirements core must contain exactly one OpenCV distribution"
        )

    distribution, wheel_version = targets[0]
    if distribution != TARGET_DISTRIBUTION:
        raise ValueError(
            f"requirements core OpenCV target must be {TARGET_DISTRIBUTION}"
        )
    version_parts = wheel_version.split(".")
    if len(version_parts) < 3:
        raise ValueError(f"invalid OpenCV wheel version: {wheel_version}")

    return OpenCvTarget(
        distribution=distribution,
        wheel_version=wheel_version,
        cv2_version=".".join(version_parts[:3]),
    )


def get_installed_opencv_distributions():
    installed = {}
    for distribution in OPENCV_DISTRIBUTIONS:
        try:
            installed[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            continue
    return installed


def _probe_cv2_version(*, run_command, python_executable):
    result = run_command(
        [python_executable, "-c", CV2_VERSION_PROBE],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    output_lines = result.stdout.strip().splitlines()
    return output_lines[-1].strip() if output_lines else None


def _installation_matches(
    target,
    *,
    get_installed_distributions,
    run_command,
    python_executable,
):
    installed = get_installed_distributions()
    cv2_version = _probe_cv2_version(
        run_command=run_command,
        python_executable=python_executable,
    )
    return (
        installed == {target.distribution: target.wheel_version}
        and cv2_version == target.cv2_version
    )


def normalize_opencv_installation(
    requirements_core_path,
    *,
    get_installed_distributions=get_installed_opencv_distributions,
    run_command=subprocess.run,
    python_executable=sys.executable,
):
    target = read_target_contract(requirements_core_path)
    if _installation_matches(
        target,
        get_installed_distributions=get_installed_distributions,
        run_command=run_command,
        python_executable=python_executable,
    ):
        print(
            "OpenCV installation already normalized: "
            f"{target.distribution}=={target.wheel_version}"
        )
        return True

    print("Reconciling conflicting or stale OpenCV wheel distributions...")
    uninstall_result = run_command(
        [
            python_executable,
            "-m",
            "pip",
            "uninstall",
            "-y",
            *OPENCV_DISTRIBUTIONS,
        ],
        check=False,
    )
    if uninstall_result.returncode != 0:
        print("Failed to remove existing OpenCV wheel distributions.")
        return False

    install_result = run_command(
        [
            python_executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--force-reinstall",
            f"{target.distribution}=={target.wheel_version}",
        ],
        check=False,
    )
    if install_result.returncode != 0:
        print(f"Failed to reinstall {target.distribution}.")
        return False

    if not _installation_matches(
        target,
        get_installed_distributions=get_installed_distributions,
        run_command=run_command,
        python_executable=python_executable,
    ):
        print("OpenCV installation validation failed after reconciliation.")
        return False

    print(
        "OpenCV installation normalized: "
        f"{target.distribution}=={target.wheel_version}"
    )
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Normalize mutually exclusive OpenCV Python distributions."
    )
    parser.add_argument("--requirements-core", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        normalized = normalize_opencv_installation(args.requirements_core)
    except (OSError, ValueError) as exc:
        print(f"OpenCV normalization configuration failed: {exc}")
        return 1
    return 0 if normalized else 1


if __name__ == "__main__":
    raise SystemExit(main())

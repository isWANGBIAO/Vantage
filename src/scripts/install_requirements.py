from pathlib import Path
import subprocess
import sys


def get_project_root():
    current = Path(__file__).resolve().parent
    for _ in range(5):
        if (current / "requirements.txt").exists():
            return current
        current = current.parent
    return Path.cwd()


def iter_requirements(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        package = line.strip()
        if package and not package.startswith("#"):
            yield package


def install_requirements(requirements_path=None):
    req_path = Path(requirements_path) if requirements_path else get_project_root() / "requirements.txt"
    failures = []

    for package in iter_requirements(req_path):
        print(f"Installing {package}...")
        result = subprocess.run([sys.executable, "-m", "pip", "install", package], check=False)
        if result.returncode != 0:
            failures.append(package)
            print(f"Failed to install {package}; continuing.\n")

    return failures


if __name__ == "__main__":
    failed_packages = install_requirements()
    if failed_packages:
        print("Packages that failed to install:")
        for package in failed_packages:
            print(f"- {package}")
        raise SystemExit(1)

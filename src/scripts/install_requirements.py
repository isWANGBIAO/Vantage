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


def install_requirements(requirements_path=None):
    req_path = Path(requirements_path) if requirements_path else get_project_root() / "requirements.txt"
    print(f"Installing requirements from {req_path}...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req_path)],
        check=False,
    )
    if result.returncode != 0:
        print(f"Failed to install requirements from {req_path}.\n")
        return [str(req_path)]
    return []


if __name__ == "__main__":
    failed_requirements_files = install_requirements()
    if failed_requirements_files:
        print("Requirements file failed to install:")
        for requirements_file in failed_requirements_files:
            print(f"- {requirements_file}")
        raise SystemExit(1)

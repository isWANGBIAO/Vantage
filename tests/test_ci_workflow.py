import json
import re
from pathlib import Path


def test_python_ci_step_isolates_vantage_runtime_dirs():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    python_step_start = workflow.index("- name: Run Python tests")
    frontend_job_start = workflow.index("  frontend:")
    python_step = workflow[python_step_start:frontend_job_start]

    required_env_vars = {
        "VANTAGE_DATA_DIR",
        "VANTAGE_CONFIG_DIR",
        "VANTAGE_HISTORY_DIR",
        "VANTAGE_LOG_DIR",
        "VANTAGE_PLOT_DIR",
        "VANTAGE_CACHE_DIR",
        "VANTAGE_RUNTIME_DIR",
        "VANTAGE_MIGRATION_DIR",
    }

    missing = [name for name in sorted(required_env_vars) if name not in python_step]
    assert not missing, f"Python CI step should isolate Vantage runtime dirs: {missing}"


def test_frontend_workflows_pin_electron_node_runtime():
    expected_electron_version = "42.6.1"
    expected_electron_range = f"^{expected_electron_version}"
    expected_node_version = "24.18.0"

    package = json.loads(Path("src/webapp/package.json").read_text(encoding="utf-8"))
    package_lock = json.loads(
        Path("src/webapp/package-lock.json").read_text(encoding="utf-8")
    )

    assert package["devDependencies"]["electron"] == expected_electron_range
    assert (
        package_lock["packages"][""]["devDependencies"]["electron"]
        == expected_electron_range
    )
    assert (
        package_lock["packages"]["node_modules/electron"]["version"]
        == expected_electron_version
    )

    for workflow_path in (
        Path(".github/workflows/ci.yml"),
        Path(".github/workflows/release.yml"),
    ):
        workflow = workflow_path.read_text(encoding="utf-8")
        configured_node_versions = re.findall(
            r'^\s+node-version:\s*["\']?([^"\'\s]+)["\']?\s*$',
            workflow,
            flags=re.MULTILINE,
        )
        assert configured_node_versions == [expected_node_version], (
            f"{workflow_path} should use the Node.js version embedded in Electron 42.6.1"
        )

    readme = Path("README.md").read_text(encoding="utf-8")
    assert 'alt="Node.js 24.18.0"' in readme
    assert "Node.js-24.18.0-" in readme
    assert 'alt="Electron 42.6.1"' in readme
    assert "Electron-42.6.1-" in readme

    requirements = readme.split("## Requirements", maxsplit=1)[1].split(
        "\n## ", maxsplit=1
    )[0]
    assert f"Node.js {expected_node_version}" in requirements

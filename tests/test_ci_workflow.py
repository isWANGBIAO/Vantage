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
    expected_electron_version = "42.8.0"
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
            f"{workflow_path} should use the Node.js version embedded in "
            f"Electron {expected_electron_version}"
        )

    readme = Path("README.md").read_text(encoding="utf-8")
    assert 'alt="Node.js 24.18.0"' in readme
    assert "Node.js-24.18.0-" in readme
    assert 'alt="Electron 42.8.0"' in readme
    assert "Electron-42.8.0-" in readme

    requirements = readme.split("## Requirements", maxsplit=1)[1].split(
        "\n## ", maxsplit=1
    )[0]
    assert f"Node.js {expected_node_version}" in requirements


def test_readme_react_badge_matches_frontend_dependency_contract():
    expected_react_version = "19.2.8"
    expected_react_range = f"^{expected_react_version}"

    package = json.loads(Path("src/webapp/package.json").read_text(encoding="utf-8"))
    package_lock = json.loads(
        Path("src/webapp/package-lock.json").read_text(encoding="utf-8")
    )

    assert package["dependencies"]["react"] == expected_react_range
    assert (
        package_lock["packages"][""]["dependencies"]["react"]
        == expected_react_range
    )
    assert (
        package_lock["packages"]["node_modules/react"]["version"]
        == expected_react_version
    )

    readme = Path("README.md").read_text(encoding="utf-8")
    assert 'alt="React 19.2.8"' in readme
    assert "React-19.2.8-" in readme


def test_readme_fastapi_badge_matches_backend_runtime_contract():
    runtime_requirements = Path("requirements-backend-runtime-gpu.txt").read_text(
        encoding="utf-8"
    )
    fastapi_versions = re.findall(
        r"^fastapi==([^;\s]+)(?:\s*;.*)?$",
        runtime_requirements,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    assert len(fastapi_versions) == 1
    expected_version = fastapi_versions[0]

    readme = Path("README.md").read_text(encoding="utf-8")
    assert f'alt="FastAPI {expected_version}"' in readme
    assert f"FastAPI-{expected_version}-" in readme


def test_release_metadata_matches_package_version():
    package = json.loads(Path("src/webapp/package.json").read_text(encoding="utf-8"))
    package_lock = json.loads(
        Path("src/webapp/package-lock.json").read_text(encoding="utf-8")
    )
    readme = Path("README.md").read_text(encoding="utf-8")
    release_workflow = Path(".github/workflows/release.yml").read_text(
        encoding="utf-8"
    )

    version = package.get("version")
    assert isinstance(version, str)
    assert re.fullmatch(
        r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)",
        version,
    )
    tag = f"v{version}"

    assert package_lock["version"] == version
    assert package_lock["packages"][""]["version"] == version
    assert f'git tag -a {tag} -m "Vantage {version}"' in readme
    assert f"git push origin {tag}" in readme
    assert (
        f"for example `{tag}` for package version `{version}`"
        in readme
    )
    assert f"for example {tag}" in release_workflow


def test_release_checksums_use_final_github_asset_names():
    release_workflow = Path(".github/workflows/release.yml").read_text(
        encoding="utf-8"
    )

    assert '$installerName = "Vantage.Setup.$version.exe"' in release_workflow
    assert '$blockmapName = "$installerName.blockmap"' in release_workflow
    assert (
        "Copy-Item -LiteralPath $asset.Source.FullName "
        "-Destination (Join-Path $assetRoot $asset.Name) -Force"
        in release_workflow
    )
    assert "- Vantage.Setup.$version.exe" in release_workflow
    assert "- Vantage.Setup.$version.exe.blockmap" in release_workflow

from pathlib import Path

from src.core.backend_environment_state import (
    BACKEND_ENVIRONMENT_STATE_NAME,
    build_backend_environment_state,
    current_platform_identity,
    current_python_identity,
    compute_backend_environment_integrity,
    write_backend_environment_state,
)
from src.core.backend_runtime_packaging import (
    build_backend_runtime_fingerprint,
    validate_packaging_python_environment,
)


def test_backend_environment_integrity_detects_stable_file_content_and_closure_drift(
    tmp_path,
):
    venv = tmp_path / ".venv-backend-runtime-gpu"
    package = venv / "Lib" / "site-packages" / "demo"
    package.mkdir(parents=True)
    module = package / "demo.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")

    original = compute_backend_environment_integrity(venv, platform_name="win32")

    module.write_text("VALUE = 999\n", encoding="utf-8")
    changed_content = compute_backend_environment_integrity(venv, platform_name="win32")
    (package / "extra.txt").write_text("extra\n", encoding="utf-8")
    changed_closure = compute_backend_environment_integrity(venv, platform_name="win32")

    assert original["digest"] != changed_content["digest"]
    assert changed_content["digest"] != changed_closure["digest"]
    assert original["file_count"] == 1
    assert changed_closure["file_count"] == 2


def test_backend_environment_integrity_ignores_regenerable_and_signing_state(
    tmp_path,
):
    venv = tmp_path / ".venv-backend-runtime-gpu"
    package = venv / "lib" / "python3.13" / "site-packages" / "demo"
    package.mkdir(parents=True)
    (package / "demo.py").write_text("VALUE = 1\n", encoding="utf-8")
    original = compute_backend_environment_integrity(venv, platform_name="darwin")

    pycache = package / "__pycache__"
    pycache.mkdir()
    (pycache / "demo.cpython-313.pyc").write_bytes(b"generated")
    (venv / BACKEND_ENVIRONMENT_STATE_NAME).write_text("{}\n", encoding="utf-8")
    (venv / ".macos-native-codesign.sha256").write_text("stamp\n", encoding="utf-8")
    staging = venv / ".vantage-codesign-staging-test"
    staging.mkdir()
    (staging / "private.so").write_bytes(b"temporary")
    native = package / "native.so"
    native.write_bytes(b"signed-version-one")
    after_generated_files = compute_backend_environment_integrity(
        venv,
        platform_name="darwin",
    )
    native.write_bytes(b"signed-version-two")
    after_native_signing = compute_backend_environment_integrity(
        venv,
        platform_name="darwin",
    )

    assert after_generated_files == original
    assert after_native_signing == original


def test_backend_environment_integrity_only_excludes_root_bookkeeping(tmp_path):
    venv = tmp_path / ".venv-backend-runtime-gpu"
    package = venv / "Lib" / "site-packages" / "demo"
    package.mkdir(parents=True)
    original = compute_backend_environment_integrity(venv, platform_name="win32")

    (package / BACKEND_ENVIRONMENT_STATE_NAME).write_text("nested\n", encoding="utf-8")
    (package / ".macos-native-codesign.sha256").write_text(
        "nested\n",
        encoding="utf-8",
    )
    nested_staging_name = package / ".vantage-codesign-staging-payload"
    nested_staging_name.mkdir()
    (nested_staging_name / "payload.txt").write_text("nested\n", encoding="utf-8")
    changed = compute_backend_environment_integrity(venv, platform_name="win32")

    assert changed["digest"] != original["digest"]
    assert changed["file_count"] == 3


def test_backend_environment_integrity_records_links_without_following_external_targets(
    tmp_path,
):
    venv = tmp_path / ".venv-backend-runtime-gpu"
    package = venv / "lib" / "site-packages"
    package.mkdir(parents=True)
    external = tmp_path / "outside.py"
    external.write_text("VALUE = 1\n", encoding="utf-8")
    link = package / "linked.py"
    try:
        link.symlink_to(external)
    except OSError:
        return

    original = compute_backend_environment_integrity(venv, platform_name="linux")
    external.write_text("VALUE = 999\n", encoding="utf-8")
    changed_external = compute_backend_environment_integrity(venv, platform_name="linux")

    assert changed_external == original
    assert original["link_count"] == 1


def test_backend_environment_integrity_rejects_a_linked_root(tmp_path):
    real_venv = tmp_path / "real-venv"
    real_venv.mkdir()
    linked_venv = tmp_path / ".venv-backend-runtime-gpu"
    try:
        linked_venv.symlink_to(real_venv, target_is_directory=True)
    except OSError:
        return

    try:
        compute_backend_environment_integrity(linked_venv)
    except ValueError as exc:
        assert "root" in str(exc).lower()
    else:
        raise AssertionError("linked backend environment root was accepted")


def test_packaging_environment_rejects_same_version_installed_file_tamper(tmp_path):
    core = tmp_path / "requirements-core.txt"
    overlay = tmp_path / "requirements-backend-runtime-gpu.txt"
    core.write_text("demo==1.0\n", encoding="utf-8")
    overlay.write_text("-r requirements-core.txt\n", encoding="utf-8")
    venv = tmp_path / ".venv-backend-runtime-gpu"
    python_path = venv / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_bytes(b"python")
    module = venv / "Lib" / "site-packages" / "demo.py"
    module.parent.mkdir(parents=True)
    module.write_text("VALUE = 1\n", encoding="utf-8")
    closure = ["demo==1.0", "pip==25.3"]
    state = build_backend_environment_state(
        core,
        overlay,
        python_identity=current_python_identity(),
        platform_identity=current_platform_identity(),
        distributions=closure,
    )
    write_backend_environment_state(venv, state)

    assert "integrity" in state
    assert validate_packaging_python_environment(
        tmp_path,
        executable=python_path,
        prefix=venv,
        distribution_closure=closure,
        python_identity=current_python_identity(),
        platform_identity=current_platform_identity(),
    ) is None

    module.write_text("VALUE = 999\n", encoding="utf-8")
    error = validate_packaging_python_environment(
        tmp_path,
        executable=python_path,
        prefix=venv,
        distribution_closure=closure,
        python_identity=current_python_identity(),
        platform_identity=current_platform_identity(),
    )

    assert "integrity" in str(error).lower()


def test_packaging_environment_reports_integrity_probe_races(tmp_path, monkeypatch):
    (tmp_path / "requirements-core.txt").write_text("demo==1.0\n", encoding="utf-8")
    (tmp_path / "requirements-backend-runtime-gpu.txt").write_text(
        "-r requirements-core.txt\n",
        encoding="utf-8",
    )
    venv = tmp_path / ".venv-backend-runtime-gpu"
    python_path = venv / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_bytes(b"python")

    def fail_integrity_probe(*_args, **_kwargs):
        raise RuntimeError("environment changed during integrity scan")

    monkeypatch.setattr(
        "src.core.backend_runtime_packaging.compute_backend_environment_integrity",
        fail_integrity_probe,
    )

    error = validate_packaging_python_environment(
        tmp_path,
        executable=python_path,
        prefix=venv,
        distribution_closure=[],
        python_identity=current_python_identity(),
        platform_identity=current_platform_identity(),
    )

    assert "could not be validated" in str(error).lower()
    assert "changed during integrity scan" in str(error)


def test_backend_runtime_fingerprint_changes_with_environment_file_integrity(tmp_path):
    venv = tmp_path / ".venv-backend-runtime-gpu"
    module = venv / "Lib" / "site-packages" / "demo.py"
    module.parent.mkdir(parents=True)
    module.write_text("VALUE = 1\n", encoding="utf-8")

    original = build_backend_runtime_fingerprint(
        tmp_path,
        resources=[],
        distribution_closure=["demo==1.0"],
    )
    module.write_text("VALUE = 999\n", encoding="utf-8")
    changed = build_backend_runtime_fingerprint(
        tmp_path,
        resources=[],
        distribution_closure=["demo==1.0"],
    )

    assert original["version"] >= 4
    assert original["environment_integrity"] != changed["environment_integrity"]
    assert original["digest"] != changed["digest"]

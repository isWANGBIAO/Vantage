from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from src.core import backend_environment_state as backend_state
from src.core.backend_environment_state import (
    BACKEND_ENVIRONMENT_STATE_NAME,
    BACKEND_ENVIRONMENT_STATE_SCHEMA_VERSION,
    LEGACY_REQUIREMENTS_STAMP_NAME,
    build_backend_environment_state,
    compute_requirements_sha256,
    environment_state_validation_error,
    load_backend_environment_state,
    normalize_distribution_closure,
    write_backend_environment_state,
)
from src.scripts.sync_backend_runtime_environment import (
    backend_runtime_python_path,
    safe_remove_backend_runtime_venv,
    synchronize_backend_runtime_environment,
)


PYTHON_IDENTITY = {
    "implementation": "CPython",
    "version": "3.13.5",
    "cache_tag": "cpython-313",
}
PLATFORM_IDENTITY = {
    "sys_platform": "win32",
    "system": "Windows",
    "machine": "AMD64",
}
CLEAN_CLOSURE = [
    "chinese-calendar==1.11.0",
    "opencv-contrib-python==4.14.0.94",
    "pip==25.3",
]


def _write_requirements(project_root: Path) -> tuple[Path, Path, Path]:
    core = project_root / "requirements-core.txt"
    overlay = project_root / "requirements-backend-runtime-gpu.txt"
    normalizer = project_root / "src" / "scripts" / "normalize_opencv_installation.py"
    normalizer.parent.mkdir(parents=True)
    core.write_text("opencv-contrib-python==4.14.0.94\n", encoding="utf-8")
    overlay.write_text("-r requirements-core.txt\n", encoding="utf-8")
    normalizer.write_text("raise SystemExit(0)\n", encoding="utf-8")
    return core, overlay, normalizer


def _write_existing_environment(
    project_root: Path,
    *,
    state_overrides: dict[str, object] | None = None,
    closure: list[str] = CLEAN_CLOSURE,
) -> tuple[Path, Path, Path, Path]:
    core, overlay, normalizer = _write_requirements(project_root)
    venv = project_root / ".venv-backend-runtime-gpu"
    python_path = backend_runtime_python_path(venv)
    python_path.parent.mkdir(parents=True)
    python_path.write_text("python", encoding="utf-8")
    state = build_backend_environment_state(
        core,
        overlay,
        python_identity=PYTHON_IDENTITY,
        platform_identity=PLATFORM_IDENTITY,
        distributions=closure,
    )
    if state_overrides:
        state.update(state_overrides)
    write_backend_environment_state(venv, state)
    return venv, core, overlay, normalizer


def _probe_payload(closure: list[str] = CLEAN_CLOSURE) -> dict[str, object]:
    return {
        "python": PYTHON_IDENTITY,
        "platform": PLATFORM_IDENTITY,
        "distributions": closure,
    }


def _successful_runner(venv: Path, commands: list[list[str]]):
    def run(command, **_kwargs):
        command = [str(part) for part in command]
        commands.append(command)
        if command[1:3] == ["-m", "venv"]:
            python_path = backend_runtime_python_path(venv)
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("python", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return run


def test_distribution_closure_is_canonical_deduplicated_and_sorted():
    assert normalize_distribution_closure(
        [
            {"name": "ZhDate", "version": "0.1"},
            ("opencv_contrib.python", "4.14.0.94"),
            "Chinese_Calendar==1.11.0",
            ("ZHDATE", "0.1"),
        ]
    ) == [
        "chinese-calendar==1.11.0",
        "opencv-contrib-python==4.14.0.94",
        "zhdate==0.1",
    ]


def test_environment_state_write_is_atomic_and_preserves_previous_state_on_replace_failure(
    tmp_path,
    monkeypatch,
):
    venv, core, overlay, _normalizer = _write_existing_environment(tmp_path)
    state_path = venv / BACKEND_ENVIRONMENT_STATE_NAME
    original = load_backend_environment_state(venv)
    replacement = build_backend_environment_state(
        core,
        overlay,
        python_identity=PYTHON_IDENTITY,
        platform_identity=PLATFORM_IDENTITY,
        distributions=[*CLEAN_CLOSURE, "new-package==1.0"],
    )

    def fail_replace(_source, _destination):
        raise OSError("replace failed")

    monkeypatch.setattr("src.core.backend_environment_state.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        write_backend_environment_state(venv, replacement)

    assert load_backend_environment_state(venv) == original
    assert not list(state_path.parent.glob(f".{state_path.name}.*.tmp"))


@pytest.mark.parametrize(
    ("mutator", "expected_reason"),
    [
        (lambda state: state.update(requirements_sha256="stale"), "requirements"),
        (
            lambda state: state.update(
                python={**PYTHON_IDENTITY, "version": "3.12.9"}
            ),
            "Python",
        ),
        (
            lambda state: state.update(
                platform={**PLATFORM_IDENTITY, "machine": "ARM64"}
            ),
            "platform",
        ),
        (
            lambda state: state.update(distributions=CLEAN_CLOSURE[:-1]),
            "distribution closure",
        ),
    ],
)
def test_environment_state_rejects_input_identity_and_closure_drift(
    tmp_path,
    mutator,
    expected_reason,
):
    core, overlay, _normalizer = _write_requirements(tmp_path)
    state = build_backend_environment_state(
        core,
        overlay,
        python_identity=PYTHON_IDENTITY,
        platform_identity=PLATFORM_IDENTITY,
        distributions=CLEAN_CLOSURE,
    )
    mutator(state)

    error = environment_state_validation_error(
        state,
        requirements_sha256=compute_requirements_sha256(core, overlay),
        python_identity=PYTHON_IDENTITY,
        platform_identity=PLATFORM_IDENTITY,
        distributions=CLEAN_CLOSURE,
    )

    assert expected_reason in error


def test_environment_state_rejects_legacy_schema():
    error = environment_state_validation_error(
        {"schema_version": BACKEND_ENVIRONMENT_STATE_SCHEMA_VERSION - 1},
        requirements_sha256="hash",
        python_identity=PYTHON_IDENTITY,
        platform_identity=PLATFORM_IDENTITY,
        distributions=CLEAN_CLOSURE,
    )

    assert "schema" in error


def test_clean_environment_is_reused_without_mutation(tmp_path):
    venv, core, overlay, normalizer = _write_existing_environment(tmp_path)
    commands: list[list[str]] = []

    outcome = synchronize_backend_runtime_environment(
        project_root=tmp_path,
        venv=venv,
        core_requirements=core,
        requirements=overlay,
        opencv_normalizer=normalizer,
        creator_python="bootstrap-python",
        creator_python_identity=PYTHON_IDENTITY,
        creator_platform_identity=PLATFORM_IDENTITY,
        run_command=_successful_runner(venv, commands),
        probe_environment=lambda _python, _run: _probe_payload(),
        pip_check=lambda _python, _run: True,
        import_check=lambda _python, _run: True,
        opencv_check=lambda _python, _core, _run: True,
    )

    assert outcome.reused is True
    assert commands == []
    assert load_backend_environment_state(venv) == outcome.state


def test_conflicting_packaging_dll_cleanup_waits_for_exclusive_lock_and_preserves_state(
    tmp_path,
):
    venv, core, overlay, normalizer = _write_existing_environment(tmp_path)
    conflicting_dll = (
        venv / "Lib" / "site-packages" / "somepkg" / "VCRUNTIME140.dll"
    )
    unrelated_dll = conflicting_dll.with_name("extension.dll")
    conflicting_dll.parent.mkdir(parents=True, exist_ok=True)
    conflicting_dll.write_bytes(b"conflicting-runtime")
    unrelated_dll.write_bytes(b"package-extension")
    state_path = venv / BACKEND_ENVIRONMENT_STATE_NAME
    original_state = load_backend_environment_state(venv)

    holder_source = """
from pathlib import Path
import sys
import time
from src.core.backend_runtime_lock import backend_runtime_lock

with backend_runtime_lock(Path(sys.argv[1]), mode="shared", timeout_seconds=2):
    print("locked", flush=True)
    time.sleep(10)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path.cwd())
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_source, str(tmp_path)],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None
    assert holder.stdout.readline().strip() == "locked"

    sync_kwargs = {
        "project_root": tmp_path,
        "venv": venv,
        "core_requirements": core,
        "requirements": overlay,
        "opencv_normalizer": normalizer,
        "creator_python": "bootstrap-python",
        "creator_python_identity": PYTHON_IDENTITY,
        "creator_platform_identity": PLATFORM_IDENTITY,
        "run_command": _successful_runner(venv, []),
        "probe_environment": lambda _python, _run: _probe_payload(),
        "pip_check": lambda _python, _run: True,
        "import_check": lambda _python, _run: True,
        "opencv_check": lambda _python, _core, _run: True,
    }
    try:
        with pytest.raises(TimeoutError, match="backend runtime lock"):
            synchronize_backend_runtime_environment(
                **sync_kwargs,
                lock_timeout_seconds=0.2,
            )
        assert conflicting_dll.exists()
        assert state_path.exists()
    finally:
        holder.terminate()
        holder.wait(timeout=5)

    outcome = synchronize_backend_runtime_environment(
        **sync_kwargs,
        lock_timeout_seconds=1,
    )

    assert outcome.reused is True
    assert not conflicting_dll.exists()
    assert unrelated_dll.exists()
    assert load_backend_environment_state(venv) == original_state == outcome.state


def test_reuse_cleanup_failure_invalidates_environment_state(tmp_path, monkeypatch):
    venv, core, overlay, normalizer = _write_existing_environment(tmp_path)
    state_path = venv / BACKEND_ENVIRONMENT_STATE_NAME

    def fail_cleanup(_project_root):
        raise OSError("cleanup failed")

    monkeypatch.setattr(
        "src.scripts.sync_backend_runtime_environment."
        "remove_conflicting_packaging_environment_libraries",
        fail_cleanup,
    )

    with pytest.raises(OSError, match="cleanup failed"):
        synchronize_backend_runtime_environment(
            project_root=tmp_path,
            venv=venv,
            core_requirements=core,
            requirements=overlay,
            opencv_normalizer=normalizer,
            creator_python="bootstrap-python",
            creator_python_identity=PYTHON_IDENTITY,
            creator_platform_identity=PLATFORM_IDENTITY,
            run_command=_successful_runner(venv, []),
            probe_environment=lambda _python, _run: _probe_payload(),
            pip_check=lambda _python, _run: True,
            import_check=lambda _python, _run: True,
            opencv_check=lambda _python, _core, _run: True,
        )

    assert not state_path.exists()


@pytest.mark.parametrize(
    "scenario",
    [
        "requirements",
        "python",
        "platform",
        "bootstrap_pip",
        "missing_distribution",
        "extra_distribution",
        "version_drift",
        "legacy_stamp",
        "pip_check",
        "forced",
    ],
)
def test_unclean_or_forced_environment_is_deleted_and_rebuilt(
    tmp_path,
    scenario,
):
    state_overrides: dict[str, object] = {}
    if scenario == "requirements":
        state_overrides["requirements_sha256"] = "stale"
    elif scenario == "python":
        state_overrides["python"] = {**PYTHON_IDENTITY, "version": "3.12.9"}
    elif scenario == "platform":
        state_overrides["platform"] = {**PLATFORM_IDENTITY, "machine": "ARM64"}
    elif scenario == "bootstrap_pip":
        state_overrides["bootstrap_pip"] = "pip==25.2"

    venv, core, overlay, normalizer = _write_existing_environment(
        tmp_path,
        state_overrides=state_overrides,
    )
    sentinel = venv / "orphaned-package.txt"
    sentinel.write_text("must disappear", encoding="utf-8")
    codesign_stamp = venv / ".macos-native-codesign.sha256"
    codesign_stamp.write_text("signed-old-environment", encoding="utf-8")
    if scenario == "legacy_stamp":
        (venv / LEGACY_REQUIREMENTS_STAMP_NAME).write_text("legacy", encoding="utf-8")

    before_closure = CLEAN_CLOSURE
    if scenario == "missing_distribution":
        before_closure = CLEAN_CLOSURE[:-1]
    elif scenario == "extra_distribution":
        before_closure = [*CLEAN_CLOSURE, "ultralytics==8.4.93"]
    elif scenario == "version_drift":
        before_closure = [*CLEAN_CLOSURE[:-1], "pip==24.0"]

    rebuilt = False
    commands: list[list[str]] = []

    def run(command, **_kwargs):
        nonlocal rebuilt
        command = [str(part) for part in command]
        commands.append(command)
        if command[1:3] == ["-m", "venv"]:
            rebuilt = True
            python_path = backend_runtime_python_path(venv)
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("python", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    pip_results = iter([False, True]) if scenario == "pip_check" else None

    outcome = synchronize_backend_runtime_environment(
        project_root=tmp_path,
        venv=venv,
        core_requirements=core,
        requirements=overlay,
        opencv_normalizer=normalizer,
        force=scenario == "forced",
        creator_python="bootstrap-python",
        creator_python_identity=PYTHON_IDENTITY,
        creator_platform_identity=PLATFORM_IDENTITY,
        run_command=run,
        probe_environment=lambda _python, _run: _probe_payload(
            CLEAN_CLOSURE if rebuilt else before_closure
        ),
        pip_check=(
            (lambda _python, _run: next(pip_results))
            if pip_results is not None
            else (lambda _python, _run: True)
        ),
        import_check=lambda _python, _run: True,
        opencv_check=lambda _python, _core, _run: True,
    )

    assert outcome.reused is False
    assert rebuilt is True
    assert not sentinel.exists()
    assert not codesign_stamp.exists()
    assert commands[0][1:3] == ["-m", "venv"]
    assert any(command[1:5] == ["-m", "pip", "install", "--upgrade"] for command in commands)
    assert any("-r" in command and str(overlay) in command for command in commands)
    assert any(str(normalizer) in command for command in commands)
    assert load_backend_environment_state(venv) == outcome.state


def test_failed_rebuild_leaves_no_valid_state(tmp_path):
    venv, core, overlay, normalizer = _write_existing_environment(tmp_path)
    commands: list[list[str]] = []

    def fail_install(command, **_kwargs):
        command = [str(part) for part in command]
        commands.append(command)
        if command[1:3] == ["-m", "venv"]:
            python_path = backend_runtime_python_path(venv)
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("python", encoding="utf-8")
        return SimpleNamespace(
            returncode=1 if "-r" in command else 0,
            stdout="",
            stderr="install failed",
        )

    with pytest.raises(RuntimeError, match="install failed"):
        synchronize_backend_runtime_environment(
            project_root=tmp_path,
            venv=venv,
            core_requirements=core,
            requirements=overlay,
            opencv_normalizer=normalizer,
            force=True,
            creator_python="bootstrap-python",
            creator_python_identity=PYTHON_IDENTITY,
            creator_platform_identity=PLATFORM_IDENTITY,
            run_command=fail_install,
            probe_environment=lambda _python, _run: _probe_payload(),
            pip_check=lambda _python, _run: True,
            import_check=lambda _python, _run: True,
            opencv_check=lambda _python, _core, _run: True,
        )

    assert not (venv / BACKEND_ENVIRONMENT_STATE_NAME).exists()


def test_failed_rebuild_output_is_bounded_and_redacted_before_error(tmp_path):
    venv, core, overlay, normalizer = _write_existing_environment(tmp_path)
    secrets = (
        "sk-1234567890abcdef",
        "bearer-secret-1234567890",
        "dXNlcjpwYXNzd29yZA==",
        "url-password-123456",
        "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
        "query-secret-1234567890",
        "npm-secret-1234567890",
        "password-secret-1234567890",
        "client-secret-1234567890",
    )
    credential_output = (
        f"api_key={secrets[0]} Authorization: Bearer {secrets[1]} "
        f"Authorization: Basic {secrets[2]} "
        f"https://alice:{secrets[3]}@example.test/private "
        f"github={secrets[4]} token={secrets[5]} NPM_TOKEN={secrets[6]} "
        f"password={secrets[7]} client_secret={secrets[8]}"
    )
    private_path = tmp_path / "private" / "credentials.json"
    observed_kwargs = []

    def fail_install(command, **kwargs):
        observed_kwargs.append(kwargs)
        command = [str(part) for part in command]
        if command[1:3] == ["-m", "venv"]:
            python_path = backend_runtime_python_path(venv)
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("python", encoding="utf-8")
        return SimpleNamespace(
            returncode=1 if "-r" in command else 0,
            stdout="",
            stderr=(f"failed at {private_path} {credential_output}\n" * 10000),
        )

    with pytest.raises(RuntimeError) as exc_info:
        synchronize_backend_runtime_environment(
            project_root=tmp_path,
            venv=venv,
            core_requirements=core,
            requirements=overlay,
            opencv_normalizer=normalizer,
            force=True,
            creator_python="bootstrap-python",
            creator_python_identity=PYTHON_IDENTITY,
            creator_platform_identity=PLATFORM_IDENTITY,
            run_command=fail_install,
            probe_environment=lambda _python, _run: _probe_payload(),
            pip_check=lambda _python, _run: True,
            import_check=lambda _python, _run: True,
            opencv_check=lambda _python, _core, _run: True,
        )

    message = str(exc_info.value)
    assert str(tmp_path) not in message
    assert all(secret not in message for secret in secrets)
    assert "<PROJECT_ROOT>" in message
    assert "[REDACTED]" in message
    assert len(message.encode("utf-8")) < 20_000
    assert observed_kwargs
    assert all(kwargs.get("timeout", 0) > 0 for kwargs in observed_kwargs)
    assert not (venv / BACKEND_ENVIRONMENT_STATE_NAME).exists()


def test_rebuild_subprocess_timeout_leaves_no_valid_state(tmp_path):
    venv, core, overlay, normalizer = _write_existing_environment(tmp_path)

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 0.01))

    with pytest.raises(RuntimeError, match="timed out"):
        synchronize_backend_runtime_environment(
            project_root=tmp_path,
            venv=venv,
            core_requirements=core,
            requirements=overlay,
            opencv_normalizer=normalizer,
            force=True,
            creator_python="bootstrap-python",
            creator_python_identity=PYTHON_IDENTITY,
            creator_platform_identity=PLATFORM_IDENTITY,
            run_command=timeout,
        )

    assert not (venv / BACKEND_ENVIRONMENT_STATE_NAME).exists()


def test_sync_refuses_to_run_from_the_target_venv(tmp_path):
    venv, core, overlay, normalizer = _write_existing_environment(tmp_path)

    with pytest.raises(ValueError, match="outside the target backend runtime venv"):
        synchronize_backend_runtime_environment(
            project_root=tmp_path,
            venv=venv,
            core_requirements=core,
            requirements=overlay,
            opencv_normalizer=normalizer,
            force=True,
            creator_python=backend_runtime_python_path(venv),
            creator_python_identity=PYTHON_IDENTITY,
            creator_platform_identity=PLATFORM_IDENTITY,
            run_command=lambda *_args, **_kwargs: pytest.fail(
                "target venv must be rejected before mutation"
            ),
        )


def test_sync_refuses_raw_target_venv_launch_path_even_when_symlink_resolves_outside(
    tmp_path,
):
    venv, core, overlay, normalizer = _write_existing_environment(tmp_path)
    target_python = backend_runtime_python_path(venv)
    outside_python = tmp_path / "system-python" / target_python.name
    outside_python.parent.mkdir()
    outside_python.write_text("system python", encoding="utf-8")
    target_python.unlink()
    target_python.symlink_to(outside_python)
    state_path = venv / BACKEND_ENVIRONMENT_STATE_NAME

    with pytest.raises(ValueError, match="outside the target backend runtime venv"):
        synchronize_backend_runtime_environment(
            project_root=tmp_path,
            venv=venv,
            core_requirements=core,
            requirements=overlay,
            opencv_normalizer=normalizer,
            force=True,
            creator_python=target_python,
            creator_python_identity=PYTHON_IDENTITY,
            creator_platform_identity=PLATFORM_IDENTITY,
            run_command=lambda *_args, **_kwargs: pytest.fail(
                "target venv must be rejected before mutation"
            ),
        )

    assert state_path.exists()


def test_sync_refuses_launch_path_whose_resolved_target_is_in_target_venv(tmp_path):
    venv, core, overlay, normalizer = _write_existing_environment(tmp_path)
    target_python = backend_runtime_python_path(venv)
    outside_link = tmp_path / "system-python-link.exe"
    outside_link.symlink_to(target_python)
    state_path = venv / BACKEND_ENVIRONMENT_STATE_NAME

    with pytest.raises(ValueError, match="outside the target backend runtime venv"):
        synchronize_backend_runtime_environment(
            project_root=tmp_path,
            venv=venv,
            core_requirements=core,
            requirements=overlay,
            opencv_normalizer=normalizer,
            force=True,
            creator_python=outside_link,
            creator_python_identity=PYTHON_IDENTITY,
            creator_platform_identity=PLATFORM_IDENTITY,
            run_command=lambda *_args, **_kwargs: pytest.fail(
                "target venv must be rejected before mutation"
            ),
        )

    assert state_path.exists()


def test_sync_refuses_creator_prefix_inside_target_venv(tmp_path):
    venv, core, overlay, normalizer = _write_existing_environment(tmp_path)
    outside_python = tmp_path / "system-python.exe"
    outside_python.write_text("system python", encoding="utf-8")
    state_path = venv / BACKEND_ENVIRONMENT_STATE_NAME

    with pytest.raises(ValueError, match="outside the target backend runtime venv"):
        synchronize_backend_runtime_environment(
            project_root=tmp_path,
            venv=venv,
            core_requirements=core,
            requirements=overlay,
            opencv_normalizer=normalizer,
            force=True,
            creator_python=outside_python,
            creator_prefix=venv,
            creator_python_identity=PYTHON_IDENTITY,
            creator_platform_identity=PLATFORM_IDENTITY,
            run_command=lambda *_args, **_kwargs: pytest.fail(
                "target venv must be rejected before mutation"
            ),
        )

    assert state_path.exists()


def test_safe_remove_allows_only_the_fixed_project_runtime_venv(tmp_path):
    expected = tmp_path / ".venv-backend-runtime-gpu"
    expected.mkdir()
    (expected / "sentinel").write_text("delete", encoding="utf-8")

    with pytest.raises(ValueError, match="dedicated backend runtime venv"):
        safe_remove_backend_runtime_venv(tmp_path, tmp_path / "other-venv")
    with pytest.raises(ValueError, match="dedicated backend runtime venv"):
        safe_remove_backend_runtime_venv(
            tmp_path,
            tmp_path / "nested" / ".venv-backend-runtime-gpu",
        )

    lock_module = __import__(
        "src.core.backend_runtime_lock",
        fromlist=["backend_runtime_lock"],
    )
    with lock_module.backend_runtime_lock(tmp_path, timeout_seconds=1):
        safe_remove_backend_runtime_venv(tmp_path, expected)
    assert not expected.exists()


def _create_directory_reparse(link: Path, target: Path) -> None:
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        return
    link.symlink_to(target, target_is_directory=True)


def _create_directory_symlink(link: Path, target: Path) -> None:
    link.symlink_to(target, target_is_directory=True)


def _runtime_lock(project_root: Path):
    lock_module = __import__(
        "src.core.backend_runtime_lock",
        fromlist=["backend_runtime_lock"],
    )
    return lock_module.backend_runtime_lock(project_root, timeout_seconds=1)


def _quarantines(project_root: Path) -> list[Path]:
    return sorted(project_root.glob(".venv-backend-runtime-gpu.quarantine-*"))


def test_root_reparse_is_quarantined_without_recursive_deletion(tmp_path):
    external = tmp_path / "external-root"
    external.mkdir()
    sentinel = external / "outside-sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    venv = tmp_path / ".venv-backend-runtime-gpu"
    _create_directory_reparse(venv, external)

    with _runtime_lock(tmp_path), pytest.warns(RuntimeWarning, match="reparse"):
        safe_remove_backend_runtime_venv(
            tmp_path,
            venv,
            remove_tree=lambda _path: pytest.fail(
                "a root reparse point must never be recursively removed"
            ),
        )

    assert not venv.exists()
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert len(_quarantines(tmp_path)) == 1


def test_nested_reparse_retains_quarantine_and_external_data(tmp_path):
    external = tmp_path / "external-nested"
    external.mkdir()
    sentinel = external / "outside-sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    venv = tmp_path / ".venv-backend-runtime-gpu"
    venv.mkdir()
    (venv / "ordinary.txt").write_text("old", encoding="utf-8")
    _create_directory_reparse(venv / "nested-link", external)

    with _runtime_lock(tmp_path), pytest.warns(RuntimeWarning, match="reparse"):
        safe_remove_backend_runtime_venv(
            tmp_path,
            venv,
            remove_tree=lambda _path: pytest.fail(
                "a tree containing a reparse point must be retained"
            ),
        )

    assert not venv.exists()
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert len(_quarantines(tmp_path)) == 1


def test_posix_venv_nested_python_symlink_is_unlinked_without_following_target(
    tmp_path,
):
    external = tmp_path / "system-python"
    external.write_text("external interpreter", encoding="utf-8")
    venv = tmp_path / ".venv-backend-runtime-gpu"
    bin_dir = venv / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(external)
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")

    with _runtime_lock(tmp_path):
        safe_remove_backend_runtime_venv(
            tmp_path,
            venv,
            platform_name="posix",
        )

    assert not venv.exists()
    assert _quarantines(tmp_path) == []
    assert external.read_text(encoding="utf-8") == "external interpreter"


def test_posix_root_symlink_is_quarantined_without_following_target(tmp_path):
    external = tmp_path / "external-posix-root"
    external.mkdir()
    sentinel = external / "outside-sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    venv = tmp_path / ".venv-backend-runtime-gpu"
    _create_directory_symlink(venv, external)

    with _runtime_lock(tmp_path), pytest.warns(RuntimeWarning, match="symbolic link"):
        safe_remove_backend_runtime_venv(
            tmp_path,
            venv,
            platform_name="posix",
            remove_tree=lambda _path: pytest.fail(
                "a root POSIX symlink must never be recursively removed"
            ),
        )

    assert not venv.exists()
    assert len(_quarantines(tmp_path)) == 1
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_reparse_swap_after_validation_is_detected_before_recursive_remove(tmp_path):
    external = tmp_path / "external-race"
    external.mkdir()
    sentinel = external / "outside-sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    venv = tmp_path / ".venv-backend-runtime-gpu"
    nested = venv / "nested"
    nested.mkdir(parents=True)
    (nested / "old.txt").write_text("old", encoding="utf-8")

    def race_hook(stage: str, quarantine: Path) -> None:
        if stage != "before_recursive_remove":
            return
        shutil.rmtree(quarantine / "nested")
        _create_directory_reparse(quarantine / "nested", external)

    with _runtime_lock(tmp_path), pytest.warns(RuntimeWarning, match="reparse"):
        safe_remove_backend_runtime_venv(
            tmp_path,
            venv,
            race_hook=race_hook,
            remove_tree=lambda _path: pytest.fail(
                "post-validation reparse replacement must prevent recursion"
            ),
        )

    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert len(_quarantines(tmp_path)) == 1


def test_root_identity_swap_is_quarantined_and_aborts_cleanup(tmp_path):
    external = tmp_path / "external-root-race"
    external.mkdir()
    sentinel = external / "outside-sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    venv = tmp_path / ".venv-backend-runtime-gpu"
    venv.mkdir()
    state_path = venv / BACKEND_ENVIRONMENT_STATE_NAME
    state_path.write_text("old state", encoding="utf-8")

    def race_hook(stage: str, path: Path) -> None:
        if stage != "after_initial_lstat":
            return
        shutil.rmtree(path)
        _create_directory_reparse(path, external)

    with _runtime_lock(tmp_path), pytest.raises(RuntimeError, match="identity"):
        safe_remove_backend_runtime_venv(
            tmp_path,
            venv,
            race_hook=race_hook,
            remove_tree=lambda _path: pytest.fail(
                "identity mismatch must abort before recursive deletion"
            ),
        )

    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert len(_quarantines(tmp_path)) == 1


def test_rename_failure_preserves_canonical_environment_and_state(tmp_path):
    venv, _core, _overlay, _normalizer = _write_existing_environment(tmp_path)
    state_path = venv / BACKEND_ENVIRONMENT_STATE_NAME

    def fail_rename(_source, _target):
        raise PermissionError("busy")

    with _runtime_lock(tmp_path), pytest.raises(RuntimeError, match="quarantine"):
        safe_remove_backend_runtime_venv(
            tmp_path,
            venv,
            rename_path=fail_rename,
            remove_tree=lambda _path: pytest.fail(
                "rename failure must not start recursive deletion"
            ),
        )

    assert venv.is_dir()
    assert state_path.exists()
    assert _quarantines(tmp_path) == []


def test_canonical_environment_is_renamed_before_recursive_cleanup(tmp_path):
    venv = tmp_path / ".venv-backend-runtime-gpu"
    venv.mkdir()
    (venv / "old.txt").write_text("old", encoding="utf-8")
    events: list[tuple[str, Path]] = []

    def rename_path(source, target):
        events.append(("rename", Path(target)))
        os.rename(source, target)

    def remove_tree(path):
        quarantine = Path(path)
        assert not venv.exists()
        assert quarantine.name.startswith(
            ".venv-backend-runtime-gpu.quarantine-"
        )
        events.append(("remove", quarantine))
        shutil.rmtree(quarantine)

    with _runtime_lock(tmp_path):
        safe_remove_backend_runtime_venv(
            tmp_path,
            venv,
            rename_path=rename_path,
            remove_tree=remove_tree,
        )

    assert [event for event, _path in events] == ["rename", "remove"]
    assert _quarantines(tmp_path) == []


def test_force_sync_cannot_probe_or_remove_during_active_consumer(tmp_path):
    venv, core, overlay, normalizer = _write_existing_environment(tmp_path)
    state_path = venv / BACKEND_ENVIRONMENT_STATE_NAME
    holder_source = """
from pathlib import Path
import sys
import time
from src.core.backend_runtime_lock import backend_runtime_lock

with backend_runtime_lock(Path(sys.argv[1]), timeout_seconds=2):
    print("locked", flush=True)
    time.sleep(10)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path.cwd())
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_source, str(tmp_path)],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None
    assert holder.stdout.readline().strip() == "locked"
    probes: list[str] = []
    removes: list[str] = []
    try:
        with pytest.raises(TimeoutError, match="backend runtime lock"):
            synchronize_backend_runtime_environment(
                project_root=tmp_path,
                venv=venv,
                core_requirements=core,
                requirements=overlay,
                opencv_normalizer=normalizer,
                force=True,
                creator_python=tmp_path / "system-python.exe",
                creator_python_identity=PYTHON_IDENTITY,
                creator_platform_identity=PLATFORM_IDENTITY,
                lock_timeout_seconds=0.2,
                probe_environment=lambda *_args: probes.append("probe"),
                remove_tree=lambda *_args: removes.append("remove"),
            )
    finally:
        holder.terminate()
        holder.wait(timeout=5)

    assert probes == []
    assert removes == []
    assert state_path.exists()

    commands: list[list[str]] = []
    outcome = synchronize_backend_runtime_environment(
        project_root=tmp_path,
        venv=venv,
        core_requirements=core,
        requirements=overlay,
        opencv_normalizer=normalizer,
        force=True,
        creator_python=tmp_path / "system-python.exe",
        creator_python_identity=PYTHON_IDENTITY,
        creator_platform_identity=PLATFORM_IDENTITY,
        lock_timeout_seconds=1,
        run_command=_successful_runner(venv, commands),
        probe_environment=lambda *_args: _probe_payload(),
        pip_check=lambda *_args: True,
        import_check=lambda *_args: True,
        opencv_check=lambda *_args: True,
    )
    assert not outcome.reused
    assert load_backend_environment_state(venv) is not None


def test_bootstrap_pip_pin_is_part_of_environment_state_identity(tmp_path):
    core, overlay, _normalizer = _write_requirements(tmp_path)
    stale_state = build_backend_environment_state(
        core,
        overlay,
        python_identity=PYTHON_IDENTITY,
        platform_identity=PLATFORM_IDENTITY,
        distributions=CLEAN_CLOSURE,
        bootstrap_pip="pip==25.2",
    )

    error = environment_state_validation_error(
        stale_state,
        requirements_sha256=compute_requirements_sha256(core, overlay),
        python_identity=PYTHON_IDENTITY,
        platform_identity=PLATFORM_IDENTITY,
        distributions=CLEAN_CLOSURE,
        bootstrap_pip=backend_state.PINNED_BOOTSTRAP_PIP,
    )

    assert BACKEND_ENVIRONMENT_STATE_SCHEMA_VERSION >= 2
    assert stale_state["bootstrap_pip"] == "pip==25.2"
    assert "bootstrap pip" in error.lower()

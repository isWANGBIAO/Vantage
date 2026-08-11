from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

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


@pytest.mark.parametrize(
    "scenario",
    [
        "requirements",
        "python",
        "platform",
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

    safe_remove_backend_runtime_venv(tmp_path, expected)
    assert not expected.exists()

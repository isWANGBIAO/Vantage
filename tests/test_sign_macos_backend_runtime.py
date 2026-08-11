from __future__ import annotations

import importlib
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _signing_module():
    return importlib.import_module("src.scripts.sign_macos_backend_runtime")


def _write_runtime(tmp_path: Path) -> tuple[Path, Path, Path, list[Path]]:
    project_root = tmp_path
    venv = project_root / ".venv-backend-runtime-gpu"
    lib_root = venv / "lib"
    nested = lib_root / "site-packages" / "sample"
    nested.mkdir(parents=True)
    libraries = [
        nested / "zeta.dylib",
        nested / "alpha.so",
    ]
    libraries[0].write_bytes(b"zeta-v1")
    libraries[1].write_bytes(b"alpha-v1")
    state_path = venv / ".vantage-backend-runtime-state.json"
    state_path.write_text('{"schema_version": 2}\n', encoding="utf-8")
    return project_root, venv, state_path, libraries


def _successful_runner(commands: list[list[str]], *, on_command=None):
    def run(command, **_kwargs):
        normalized = [str(part) for part in command]
        commands.append(normalized)
        if on_command is not None:
            on_command(normalized)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return run


def _write_matching_stamp(module, venv: Path, state_path: Path) -> Path:
    stamp_path = venv / ".macos-native-codesign.sha256"
    state = module.build_macos_backend_codesign_state(venv, state_path)
    module.write_macos_backend_codesign_state(stamp_path, state)
    return stamp_path


def _codesign_commands(commands: list[list[str]]) -> list[list[str]]:
    return [command for command in commands if command and command[0] == "codesign"]


def test_codesign_state_uses_stable_relative_file_closure_and_state_hash(tmp_path):
    module = _signing_module()
    _project_root, venv, state_path, _libraries = _write_runtime(tmp_path)

    state = module.build_macos_backend_codesign_state(venv, state_path)

    assert state["schema_version"] == 1
    assert state["backend_environment_state_sha256"] == hashlib.sha256(
        state_path.read_bytes()
    ).hexdigest()
    assert state["native_libraries"] == [
        {
            "path": "lib/site-packages/sample/alpha.so",
            "size": len(b"alpha-v1"),
            "sha256": hashlib.sha256(b"alpha-v1").hexdigest(),
        },
        {
            "path": "lib/site-packages/sample/zeta.dylib",
            "size": len(b"zeta-v1"),
            "sha256": hashlib.sha256(b"zeta-v1").hexdigest(),
        },
    ]


def test_signing_commands_run_while_backend_runtime_lock_is_held(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, _libraries = _write_runtime(tmp_path)
    stamp_path = venv / ".macos-native-codesign.sha256"
    commands: list[list[str]] = []

    def assert_lock_held(_command: list[str]) -> None:
        from src.core.backend_runtime_lock import backend_runtime_lock_is_held

        assert backend_runtime_lock_is_held(project_root)

    module.sign_macos_backend_runtime(
        project_root=project_root,
        venv=venv,
        state_path=state_path,
        stamp_path=stamp_path,
        run_command=_successful_runner(commands, on_command=assert_lock_held),
        system_name="Darwin",
    )

    assert _codesign_commands(commands)


def test_matching_stamp_still_verifies_every_library_without_resigning(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    stamp_path = _write_matching_stamp(module, venv, state_path)
    commands: list[list[str]] = []

    outcome = module.sign_macos_backend_runtime(
        project_root=project_root,
        venv=venv,
        state_path=state_path,
        stamp_path=stamp_path,
        run_command=_successful_runner(commands),
        system_name="Darwin",
    )

    codesign_commands = _codesign_commands(commands)
    assert outcome.reused is True
    assert len(codesign_commands) == len(libraries)
    assert all("--verify" in command for command in codesign_commands)
    assert all("--strict" in command for command in codesign_commands)
    assert all("--verbose=2" in command for command in codesign_commands)
    assert not any("--force" in command for command in codesign_commands)
    assert [Path(command[-1]).name for command in codesign_commands] == [
        "alpha.so",
        "zeta.dylib",
    ]


def test_library_byte_change_invalidates_stamp_before_resigning(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    stamp_path = _write_matching_stamp(module, venv, state_path)
    libraries[1].write_bytes(b"alpha-v2")
    commands: list[list[str]] = []

    def assert_invalidated_before_sign(command: list[str]) -> None:
        if "--force" in command:
            assert not stamp_path.exists()

    outcome = module.sign_macos_backend_runtime(
        project_root=project_root,
        venv=venv,
        state_path=state_path,
        stamp_path=stamp_path,
        run_command=_successful_runner(
            commands,
            on_command=assert_invalidated_before_sign,
        ),
        system_name="Darwin",
    )

    codesign_commands = _codesign_commands(commands)
    assert outcome.reused is False
    sign_commands = [command for command in codesign_commands if "--force" in command]
    assert len(sign_commands) == 2
    assert all(
        command[1:-1] == ["--force", "--sign", "-", "--timestamp=none"]
        for command in sign_commands
    )
    assert len([command for command in codesign_commands if "--verify" in command]) == 2
    payload = json.loads(stamp_path.read_text(encoding="utf-8"))
    assert payload == module.build_macos_backend_codesign_state(venv, state_path)


def test_environment_state_change_forces_resigning(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, _libraries = _write_runtime(tmp_path)
    stamp_path = _write_matching_stamp(module, venv, state_path)
    state_path.write_text('{"schema_version": 2, "changed": true}\n', encoding="utf-8")
    commands: list[list[str]] = []

    outcome = module.sign_macos_backend_runtime(
        project_root=project_root,
        venv=venv,
        state_path=state_path,
        stamp_path=stamp_path,
        run_command=_successful_runner(commands),
        system_name="Darwin",
    )

    assert outcome.reused is False
    assert any("--force" in command for command in _codesign_commands(commands))


def test_failed_clean_verification_rebuilds_signature_and_stamp(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, _libraries = _write_runtime(tmp_path)
    stamp_path = _write_matching_stamp(module, venv, state_path)
    commands: list[list[str]] = []
    verification_attempt = 0

    def run(command, **_kwargs):
        nonlocal verification_attempt
        normalized = [str(part) for part in command]
        commands.append(normalized)
        if normalized[0] == "codesign" and "--force" in normalized:
            assert not stamp_path.exists()
        if normalized[0] == "codesign" and "--verify" in normalized:
            verification_attempt += 1
            if verification_attempt == 1:
                return SimpleNamespace(
                    returncode=3,
                    stdout="",
                    stderr="invalid signature",
                )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    outcome = module.sign_macos_backend_runtime(
        project_root=project_root,
        venv=venv,
        state_path=state_path,
        stamp_path=stamp_path,
        run_command=run,
        system_name="Darwin",
    )

    assert outcome.reused is False
    assert any("--force" in command for command in _codesign_commands(commands))
    assert stamp_path.is_file()


def test_sign_failure_leaves_no_valid_stamp(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    stamp_path = _write_matching_stamp(module, venv, state_path)
    libraries[0].write_bytes(b"changed")

    def run(command, **_kwargs):
        normalized = [str(part) for part in command]
        return SimpleNamespace(
            returncode=(
                9
                if normalized[0] == "codesign" and "--force" in normalized
                else 0
            ),
            stdout="",
            stderr="sign failed",
        )

    with pytest.raises(RuntimeError, match="sign"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=run,
            system_name="Darwin",
        )

    assert not stamp_path.exists()


def test_post_sign_verification_failure_leaves_no_valid_stamp(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    stamp_path = _write_matching_stamp(module, venv, state_path)
    libraries[0].write_bytes(b"changed")

    def run(command, **_kwargs):
        normalized = [str(part) for part in command]
        failed_verify = normalized[0] == "codesign" and "--verify" in normalized
        return SimpleNamespace(
            returncode=11 if failed_verify else 0,
            stdout="",
            stderr="verify failed",
        )

    with pytest.raises(RuntimeError, match="verify"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=run,
            system_name="Darwin",
        )

    assert not stamp_path.exists()


def test_atomic_stamp_replace_failure_removes_temporary_and_valid_stamp(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    stamp_path = _write_matching_stamp(module, venv, state_path)
    libraries[0].write_bytes(b"changed")

    def fail_replace(_source, _target):
        raise PermissionError("replace denied")

    with pytest.raises(PermissionError, match="replace denied"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=_successful_runner([]),
            replace_file=fail_replace,
            system_name="Darwin",
        )

    assert not stamp_path.exists()
    assert list(stamp_path.parent.glob(f".{stamp_path.name}.*.tmp")) == []

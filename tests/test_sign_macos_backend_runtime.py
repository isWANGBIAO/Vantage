from __future__ import annotations

import importlib
import hashlib
import json
import os
from pathlib import Path
import subprocess
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


def _create_directory_link(link: Path, target: Path) -> None:
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


def _create_file_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")


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


def test_signer_rejects_runtime_root_link_without_reading_external_files(tmp_path):
    module = _signing_module()
    external_root = tmp_path / "external-runtime"
    external_lib = external_root / "lib"
    external_lib.mkdir(parents=True)
    external_native = external_lib / "outside.so"
    external_native.write_bytes(b"outside")
    (external_root / ".vantage-backend-runtime-state.json").write_text(
        '{"schema_version": 2}\n',
        encoding="utf-8",
    )
    venv = tmp_path / ".venv-backend-runtime-gpu"
    _create_directory_link(venv, external_root)

    with pytest.raises(ValueError, match="root.*link|root.*reparse"):
        module.sign_macos_backend_runtime(
            project_root=tmp_path,
            venv=venv,
            state_path=venv / ".vantage-backend-runtime-state.json",
            stamp_path=venv / ".macos-native-codesign.sha256",
            run_command=lambda *_args, **_kwargs: pytest.fail(
                "an unsafe runtime root must be rejected before commands run"
            ),
            system_name="Darwin",
        )

    assert external_native.read_bytes() == b"outside"


def test_signer_rejects_linked_library_root_without_following_external_files(tmp_path):
    module = _signing_module()
    venv = tmp_path / ".venv-backend-runtime-gpu"
    venv.mkdir()
    state_path = venv / ".vantage-backend-runtime-state.json"
    state_path.write_text('{"schema_version": 2}\n', encoding="utf-8")
    external_lib = tmp_path / "external-lib"
    external_lib.mkdir()
    external_native = external_lib / "outside.dylib"
    external_native.write_bytes(b"outside")
    _create_directory_link(venv / "lib", external_lib)

    with pytest.raises(ValueError, match="library.*link|library.*reparse"):
        module.sign_macos_backend_runtime(
            project_root=tmp_path,
            venv=venv,
            state_path=state_path,
            stamp_path=venv / ".macos-native-codesign.sha256",
            run_command=lambda *_args, **_kwargs: pytest.fail(
                "an unsafe library root must be rejected before commands run"
            ),
            system_name="Darwin",
        )

    assert external_native.read_bytes() == b"outside"


def test_signer_rejects_native_file_link_without_hashing_external_target(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    external_native = tmp_path / "outside.so"
    external_native.write_bytes(b"outside")
    libraries[1].unlink()
    _create_file_link(libraries[1], external_native)

    with pytest.raises(ValueError, match="native.*link|native.*reparse"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=venv / ".macos-native-codesign.sha256",
            run_command=lambda *_args, **_kwargs: pytest.fail(
                "an unsafe native file must be rejected before commands run"
            ),
            system_name="Darwin",
        )

    assert external_native.read_bytes() == b"outside"


def test_native_file_swap_after_scan_is_rejected_before_codesign(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    stamp_path = venv / ".macos-native-codesign.sha256"
    external_native = tmp_path / "outside.so"
    external_native.write_bytes(b"outside")
    commands: list[list[str]] = []

    def run(command, **_kwargs):
        normalized = [str(part) for part in command]
        commands.append(normalized)
        if normalized[0] == "xattr":
            libraries[1].unlink()
            _create_file_link(libraries[1], external_native)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises((RuntimeError, ValueError), match="identity|link|reparse|escaped"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=run,
            system_name="Darwin",
        )

    assert not _codesign_commands(commands)
    assert not stamp_path.exists()
    assert external_native.read_bytes() == b"outside"


def test_native_file_swap_after_sign_is_rejected_before_verification(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    stamp_path = venv / ".macos-native-codesign.sha256"
    external_native = tmp_path / "outside.so"
    external_native.write_bytes(b"outside")
    commands: list[list[str]] = []
    swapped = False

    def run(command, **_kwargs):
        nonlocal swapped
        normalized = [str(part) for part in command]
        commands.append(normalized)
        if normalized[0] == "codesign" and "--force" in normalized and not swapped:
            target = Path(normalized[-1])
            target.unlink()
            _create_file_link(target, external_native)
            swapped = True
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises((RuntimeError, ValueError), match="identity|link|reparse|escaped"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=run,
            system_name="Darwin",
        )

    verify_commands = [
        command
        for command in _codesign_commands(commands)
        if "--verify" in command
    ]
    assert verify_commands == []
    assert not stamp_path.exists()
    assert external_native.read_bytes() == b"outside"

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
    verify_commands = [
        command for command in codesign_commands if "--verify" in command
    ]
    assert len(verify_commands) == 4
    if os.name != "nt":
        assert all(not Path(command[-1]).is_absolute() for command in verify_commands)
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

    def fail_replace(_source, _target, **_kwargs):
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


def test_signer_rejects_hard_linked_native_before_external_target_can_be_signed(
    tmp_path,
):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    external_native = tmp_path / "outside.so"
    external_native.write_bytes(b"outside")
    libraries[1].unlink()
    os.link(external_native, libraries[1])

    with pytest.raises(ValueError, match="native.*hard link|native.*link count"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=venv / ".macos-native-codesign.sha256",
            run_command=lambda *_args, **_kwargs: pytest.fail(
                "a hard-linked native file must be rejected before commands run"
            ),
            system_name="Darwin",
        )

    assert external_native.read_bytes() == b"outside"


def test_signer_rejects_hard_linked_environment_state_before_reading_it(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, _libraries = _write_runtime(tmp_path)
    external_state = tmp_path / "outside-state.json"
    external_state.write_text('{"outside": true}\n', encoding="utf-8")
    state_path.unlink()
    os.link(external_state, state_path)

    with pytest.raises(ValueError, match="state.*hard link|state.*link count"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=venv / ".macos-native-codesign.sha256",
            run_command=lambda *_args, **_kwargs: pytest.fail(
                "a hard-linked state must be rejected before commands run"
            ),
            system_name="Darwin",
        )

    assert external_state.read_text(encoding="utf-8") == '{"outside": true}\n'


def test_signer_rejects_hard_linked_signature_stamp_before_reading_it(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, _libraries = _write_runtime(tmp_path)
    stamp_path = _write_matching_stamp(module, venv, state_path)
    external_stamp = tmp_path / "outside-stamp.json"
    stamp_path.replace(external_stamp)
    os.link(external_stamp, stamp_path)

    with pytest.raises(ValueError, match="stamp.*hard link|stamp.*link count"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=lambda *_args, **_kwargs: pytest.fail(
                "a hard-linked stamp must be rejected before commands run"
            ),
            system_name="Darwin",
        )

    assert external_stamp.is_file()


def test_xattr_cleanup_is_scoped_to_each_verified_native_file(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    commands: list[list[str]] = []

    module.sign_macos_backend_runtime(
        project_root=project_root,
        venv=venv,
        state_path=state_path,
        stamp_path=venv / ".macos-native-codesign.sha256",
        run_command=_successful_runner(commands),
        system_name="Darwin",
    )

    xattr_commands = [command for command in commands if command[0] == "xattr"]
    assert [Path(command[-1]).name for command in xattr_commands] == [
        path.name for path in sorted(libraries, key=lambda path: path.name)
    ]
    if os.name != "nt":
        assert all(not Path(command[-1]).is_absolute() for command in xattr_commands)
    assert all(Path(command[-1]) not in libraries for command in xattr_commands)
    assert all("-r" not in command and "-cr" not in command for command in xattr_commands)


def test_native_hardlink_swap_during_xattr_is_rejected_before_codesign(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, _libraries = _write_runtime(tmp_path)
    stamp_path = venv / ".macos-native-codesign.sha256"
    external_native = tmp_path / "outside.so"
    external_native.write_bytes(b"outside")
    commands: list[list[str]] = []
    swapped = False

    def run(command, **kwargs):
        nonlocal swapped
        normalized = [str(part) for part in command]
        commands.append(normalized)
        if normalized[0] == "xattr" and not swapped:
            directory_fd = kwargs.get("working_directory_fd")
            os.unlink(normalized[-1], dir_fd=directory_fd)
            os.link(
                external_native,
                normalized[-1],
                dst_dir_fd=directory_fd,
            )
            swapped = True
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises((RuntimeError, ValueError), match="identity|hard link|link count"):
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


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX inherited directory fds")
def test_staged_xattr_is_fd_bound_during_venv_root_swap(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, _libraries = _write_runtime(tmp_path)
    stamp_path = venv / ".macos-native-codesign.sha256"
    moved_venv = venv.with_name(venv.name + "-moved")
    external_venv = tmp_path / "external-venv"
    external_venv.mkdir()
    observed = {"directory_fd": None, "external_target": None}

    def run(command, **kwargs):
        normalized = [str(part) for part in command]
        if normalized[0] == "xattr" and observed["external_target"] is None:
            staged_matches = list(
                venv.glob(f".vantage-codesign-staging-*/**/{normalized[-1]}")
            )
            assert len(staged_matches) == 1
            relative_stage = staged_matches[0].relative_to(venv)
            venv.rename(moved_venv)
            external_target = external_venv / relative_stage
            external_target.parent.mkdir(parents=True)
            external_target.write_bytes(b"external-sentinel")
            venv.symlink_to(external_venv, target_is_directory=True)
            directory_fd = kwargs.get("working_directory_fd")
            observed["directory_fd"] = directory_fd
            observed["external_target"] = external_target
            descriptor = os.open(
                normalized[-1],
                os.O_WRONLY | os.O_TRUNC,
                dir_fd=directory_fd,
            )
            try:
                os.write(descriptor, b"private-stage-updated")
            finally:
                os.close(descriptor)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises((RuntimeError, ValueError), match="changed|identity|root"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=run,
            system_name="Darwin",
        )

    assert observed["directory_fd"] is not None
    assert observed["external_target"].read_bytes() == b"external-sentinel"
    assert not list(moved_venv.glob(".vantage-codesign-staging-*"))
    assert not (moved_venv / stamp_path.name).exists()


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX inherited directory fds")
def test_cached_verify_is_fd_bound_during_venv_root_swap(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    stamp_path = _write_matching_stamp(module, venv, state_path)
    moved_venv = venv.with_name(venv.name + "-moved")
    external_venv = tmp_path / "external-venv"
    external_venv.mkdir()
    expected_bytes = sorted(libraries, key=lambda path: path.name)[0].read_bytes()
    observed = {"directory_fd": None, "read_bytes": None, "external": None}

    def run(command, **kwargs):
        normalized = [str(part) for part in command]
        if normalized[0] == "codesign" and observed["external"] is None:
            source_matches = list(venv.rglob(normalized[-1]))
            assert len(source_matches) == 1
            relative_source = source_matches[0].relative_to(venv)
            venv.rename(moved_venv)
            external_source = external_venv / relative_source
            external_source.parent.mkdir(parents=True)
            external_source.write_bytes(b"external-sentinel")
            venv.symlink_to(external_venv, target_is_directory=True)
            directory_fd = kwargs.get("working_directory_fd")
            observed["directory_fd"] = directory_fd
            observed["external"] = external_source
            descriptor = os.open(
                normalized[-1],
                os.O_RDONLY,
                dir_fd=directory_fd,
            )
            try:
                observed["read_bytes"] = os.read(descriptor, 1024 * 1024)
            finally:
                os.close(descriptor)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises((RuntimeError, ValueError), match="changed|identity|root"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=run,
            system_name="Darwin",
        )

    assert observed["directory_fd"] is not None
    assert observed["read_bytes"] == expected_bytes
    assert observed["external"].read_bytes() == b"external-sentinel"
    assert not (moved_venv / stamp_path.name).exists()


@pytest.mark.parametrize(
    "mutation",
    ["add", "delete", "replace", "bytes", "state-bytes"],
)
def test_cached_verification_rejects_closure_or_byte_mutation_after_verify(
    tmp_path,
    mutation,
):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    stamp_path = _write_matching_stamp(module, venv, state_path)
    commands: list[list[str]] = []
    verify_count = 0

    def mutate_verified_runtime() -> None:
        if mutation == "state-bytes":
            state_path.write_text('{"changed": true}\n', encoding="utf-8")
            return
        target = libraries[0]
        if mutation == "add":
            target.with_name("new.so").write_bytes(b"new")
        elif mutation == "delete":
            target.unlink()
        elif mutation == "replace":
            replacement = target.with_name("replacement.tmp")
            replacement.write_bytes(b"replacement")
            os.replace(replacement, target)
        else:
            target.write_bytes(b"changed-in-place")

    def run(command, **_kwargs):
        nonlocal verify_count
        normalized = [str(part) for part in command]
        commands.append(normalized)
        if normalized[0] == "codesign" and "--verify" in normalized:
            verify_count += 1
            if verify_count == len(libraries):
                mutate_verified_runtime()
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises(
        RuntimeError,
        match="closure|identity|content|changed|unavailable",
    ):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=run,
            system_name="Darwin",
        )

    assert not stamp_path.exists()
    assert not any("--force" in command for command in _codesign_commands(commands))


def test_post_sign_verification_rejects_new_native_before_writing_stamp(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    stamp_path = venv / ".macos-native-codesign.sha256"
    commands: list[list[str]] = []
    verify_count = 0

    def run(command, **_kwargs):
        nonlocal verify_count
        normalized = [str(part) for part in command]
        commands.append(normalized)
        if normalized[0] == "codesign" and "--verify" in normalized:
            verify_count += 1
            if verify_count == len(libraries):
                libraries[0].with_name("new.so").write_bytes(b"new")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises(RuntimeError, match="closure|identity|content|changed"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=run,
            system_name="Darwin",
        )

    assert not stamp_path.exists()


def test_cached_verification_rejects_stamp_replacement_during_verify(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    stamp_path = _write_matching_stamp(module, venv, state_path)
    verify_count = 0

    def run(command, **_kwargs):
        nonlocal verify_count
        normalized = [str(part) for part in command]
        if normalized[0] == "codesign" and "--verify" in normalized:
            verify_count += 1
            if verify_count == len(libraries):
                replacement = stamp_path.with_suffix(".replacement")
                replacement.write_text('{"forged": true}\n', encoding="utf-8")
                os.replace(replacement, stamp_path)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises(RuntimeError, match="stamp.*identity|stamp.*changed"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=run,
            system_name="Darwin",
        )

    assert not stamp_path.exists()


def test_runtime_mutation_during_stamp_replace_is_detected_and_stamp_removed(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    stamp_path = venv / ".macos-native-codesign.sha256"

    def replace_then_mutate(source, target, **kwargs):
        os.replace(source, target, **kwargs)
        libraries[0].write_bytes(b"changed-after-verify")

    with pytest.raises(RuntimeError, match="closure|identity|content|changed"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=_successful_runner([]),
            replace_file=replace_then_mutate,
            system_name="Darwin",
        )

    assert not stamp_path.exists()


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX dirfd replacement")
def test_runtime_root_swap_during_stamp_replace_cannot_touch_external_stamp(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, _libraries = _write_runtime(tmp_path)
    stamp_path = venv / ".macos-native-codesign.sha256"
    moved_venv = tmp_path / "moved-runtime"
    external = tmp_path / "external-runtime"
    external.mkdir()
    external_stamp = external / stamp_path.name
    external_stamp.write_bytes(b"DO-NOT-TOUCH")
    real_replace = os.replace
    swapped = False

    def swap_root_then_replace(source, target, **kwargs):
        nonlocal swapped
        if not swapped:
            swapped = True
            venv.rename(moved_venv)
            venv.symlink_to(external, target_is_directory=True)
            if not kwargs:
                (external / Path(source).name).write_bytes(b"attacker-temp")
        return real_replace(source, target, **kwargs)

    with pytest.raises((RuntimeError, ValueError), match="root|link|identity"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=_successful_runner([]),
            replace_file=swap_root_then_replace,
            system_name="Darwin",
        )

    assert swapped is True
    assert external_stamp.read_bytes() == b"DO-NOT-TOUCH"
    assert not list(moved_venv.glob(".vantage-codesign-staging-*"))
    assert not (moved_venv / stamp_path.name).exists()


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

    def run(command, **kwargs):
        nonlocal swapped
        normalized = [str(part) for part in command]
        commands.append(normalized)
        if normalized[0] == "codesign" and "--force" in normalized and not swapped:
            directory_fd = kwargs.get("working_directory_fd")
            if directory_fd is None:
                target = Path(normalized[-1])
                target.unlink()
                _create_file_link(target, external_native)
            else:
                os.unlink(normalized[-1], dir_fd=directory_fd)
                os.symlink(
                    external_native,
                    normalized[-1],
                    dir_fd=directory_fd,
                )
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


def test_codesign_path_swap_cannot_modify_external_hardlink_target(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    stamp_path = venv / ".macos-native-codesign.sha256"
    external_native = tmp_path / "outside.so"
    external_native.write_bytes(b"outside-sentinel")
    swapped = False

    def run(command, **_kwargs):
        nonlocal swapped
        normalized = [str(part) for part in command]
        if normalized[0] == "codesign" and "--force" in normalized and not swapped:
            original = next(
                library
                for library in libraries
                if library.name == Path(normalized[-1]).name
            )
            original.unlink()
            os.link(external_native, original)
            Path(normalized[-1]).write_bytes(b"codesign-mutated-target")
            swapped = True
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises((RuntimeError, ValueError), match="identity|hard link|link count"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=run,
            system_name="Darwin",
        )

    assert external_native.read_bytes() == b"outside-sentinel"
    assert not stamp_path.exists()


def test_xattr_path_swap_cannot_modify_external_hardlink_target(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    stamp_path = venv / ".macos-native-codesign.sha256"
    external_native = tmp_path / "outside-xattr.so"
    external_native.write_bytes(b"outside-xattr-sentinel")
    swapped = False

    def run(command, **_kwargs):
        nonlocal swapped
        normalized = [str(part) for part in command]
        if normalized[0] == "xattr" and not swapped:
            original = next(
                library
                for library in libraries
                if library.name == Path(normalized[-1]).name
            )
            original.unlink()
            os.link(external_native, original)
            Path(normalized[-1]).write_bytes(b"xattr-mutated-target")
            swapped = True
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises((RuntimeError, ValueError), match="identity|hard link|link count"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=run,
            system_name="Darwin",
        )

    assert external_native.read_bytes() == b"outside-xattr-sentinel"
    assert not stamp_path.exists()


def test_codesign_may_replace_private_staging_inode_before_atomic_install(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    stamp_path = venv / ".macos-native-codesign.sha256"

    def run(command, **kwargs):
        normalized = [str(part) for part in command]
        if normalized[0] == "codesign" and "--force" in normalized:
            directory_fd = kwargs.get("working_directory_fd")
            if directory_fd is None:
                target = Path(normalized[-1])
                replacement = target.with_suffix(target.suffix + ".replacement")
                replacement.write_bytes(target.read_bytes() + b"-signed")
                os.replace(replacement, target)
            else:
                source_fd = os.open(normalized[-1], os.O_RDONLY, dir_fd=directory_fd)
                try:
                    signed_bytes = os.read(source_fd, 1024 * 1024) + b"-signed"
                finally:
                    os.close(source_fd)
                replacement_name = normalized[-1] + ".replacement"
                replacement_fd = os.open(
                    replacement_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=directory_fd,
                )
                try:
                    os.write(replacement_fd, signed_bytes)
                finally:
                    os.close(replacement_fd)
                os.replace(
                    replacement_name,
                    normalized[-1],
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
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
    assert all(library.read_bytes().endswith(b"-signed") for library in libraries)
    assert stamp_path.is_file()


def test_staging_root_replacement_is_preserved_during_safe_cleanup(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, _libraries = _write_runtime(tmp_path)
    stamp_path = venv / ".macos-native-codesign.sha256"
    replacement_sentinel: Path | None = None

    def run(command, **_kwargs):
        nonlocal replacement_sentinel
        normalized = [str(part) for part in command]
        if normalized[0] == "codesign" and "--force" in normalized:
            staging_roots = list(venv.glob(".vantage-codesign-staging-*"))
            assert len(staging_roots) == 1
            staging_root = staging_roots[0]
            moved_root = staging_root.with_name(staging_root.name + "-moved")
            staging_root.rename(moved_root)
            staging_root.mkdir()
            replacement_sentinel = staging_root / "replacement-sentinel.txt"
            replacement_sentinel.write_text("preserve", encoding="utf-8")
            raise RuntimeError("staging root swapped")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises(RuntimeError, match="staging root swapped"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=run,
            system_name="Darwin",
        )

    assert replacement_sentinel is not None
    assert replacement_sentinel.read_text(encoding="utf-8") == "preserve"
    assert not stamp_path.exists()


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX dir_fd semantics")
def test_staging_parent_swap_before_open_cannot_create_external_file(
    tmp_path,
    monkeypatch,
):
    module = _signing_module()
    _project_root, venv, state_path, _libraries = _write_runtime(tmp_path)
    snapshot = module._build_signing_snapshot(venv, state_path)
    state = module._codesign_state_from_snapshot(venv, state_path, snapshot)
    expected_hash = {
        entry["path"]: entry["sha256"] for entry in state["native_libraries"]
    }
    staging_root, staging_identity = module._create_private_staging_root(
        venv,
        snapshot,
    )
    external = tmp_path / "external-staging-parent"
    external.mkdir()
    real_open = module.os.open
    swapped = False

    def swap_parent_before_target_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if (
            not swapped
            and dir_fd is not None
            and flags & os.O_CREAT
            and Path(path).name == snapshot.libraries[0].path.name
        ):
            staging_parent = staging_root / "0000"
            staging_parent.rename(staging_root / "0000-moved")
            staging_parent.symlink_to(external, target_is_directory=True)
            swapped = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(module.os, "open", swap_parent_before_target_open)
    library = snapshot.libraries[0]
    try:
        with pytest.raises((RuntimeError, ValueError), match="staging|containment|link"):
            module._copy_native_library_to_staging(
                venv,
                snapshot,
                library,
                staging_root=staging_root,
                staging_root_identity=staging_identity,
                index=0,
                expected_sha256=expected_hash[
                    library.path.relative_to(venv).as_posix()
                ],
            )
    finally:
        monkeypatch.setattr(module.os, "open", real_open)
        module._cleanup_private_staging_root(
            venv,
            snapshot.venv_identity,
            staging_root,
            staging_identity,
        )

    assert list(external.iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX in-place race")
def test_transient_source_byte_mutation_cannot_poison_staged_copy(
    tmp_path,
    monkeypatch,
):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    stamp_path = venv / ".macos-native-codesign.sha256"
    target = sorted(libraries, key=lambda path: path.name)[0]
    original = target.read_bytes()
    real_read = module.os.read
    injected = False

    def transient_read(descriptor, length):
        nonlocal injected
        if not injected:
            target.write_bytes(b"poisoned")
            poisoned = real_read(descriptor, length)
            target.write_bytes(original)
            injected = True
            return poisoned
        return real_read(descriptor, length)

    monkeypatch.setattr(module.os, "read", transient_read)
    with pytest.raises(RuntimeError, match="content changed while staging"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=_successful_runner([]),
            system_name="Darwin",
        )

    assert target.read_bytes() == original
    assert not stamp_path.exists()


def test_codesign_failure_output_is_bounded_redacted_and_has_a_timeout(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    stamp_path = _write_matching_stamp(module, venv, state_path)
    libraries[0].write_bytes(b"changed")
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
    observed_timeouts = []

    def run(command, **kwargs):
        normalized = [str(part) for part in command]
        observed_timeouts.append(kwargs.get("timeout"))
        failed_sign = normalized[0] == "codesign" and "--force" in normalized
        return SimpleNamespace(
            returncode=7 if failed_sign else 0,
            stdout="",
            stderr=(f"failure at {project_root} {credential_output}\n" * 10000),
        )

    with pytest.raises(RuntimeError) as exc_info:
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=run,
            system_name="Darwin",
        )

    message = str(exc_info.value)
    assert str(project_root) not in message
    assert all(secret not in message for secret in secrets)
    assert "<PROJECT_ROOT>" in message
    assert "[REDACTED]" in message
    assert len(message.encode("utf-8")) < 20_000
    assert observed_timeouts
    assert all(timeout and timeout > 0 for timeout in observed_timeouts)
    assert not stamp_path.exists()


def test_codesign_timeout_removes_the_signature_stamp(tmp_path):
    module = _signing_module()
    project_root, venv, state_path, libraries = _write_runtime(tmp_path)
    stamp_path = _write_matching_stamp(module, venv, state_path)
    libraries[0].write_bytes(b"changed")

    def timeout(command, **kwargs):
        normalized = [str(part) for part in command]
        if normalized[0] == "codesign":
            raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 0.01))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises(RuntimeError, match="timed out"):
        module.sign_macos_backend_runtime(
            project_root=project_root,
            venv=venv,
            state_path=state_path,
            stamp_path=stamp_path,
            run_command=timeout,
            system_name="Darwin",
        )

    assert not stamp_path.exists()

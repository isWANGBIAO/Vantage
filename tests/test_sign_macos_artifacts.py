from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


MACHO_64_MAGIC = b"\xcf\xfa\xed\xfe"


def _module():
    return importlib.import_module("src.scripts.sign_macos_artifacts")


def _write_frontend_tree(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    project_root = tmp_path
    webapp = project_root / "src" / "webapp"
    root = webapp / "node_modules"
    native = root / "sample" / "addon.node"
    native.parent.mkdir(parents=True)
    native.write_bytes(MACHO_64_MAGIC + b"native-v1")
    package_lock = webapp / "package-lock.json"
    package_lock.write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    stamp = root / ".macos-native-codesign.sha256"
    return project_root, root, native, stamp


def _successful_runner(commands: list[list[str]], *, on_command=None):
    def run(command, **kwargs):
        normalized = [str(part) for part in command]
        commands.append(normalized)
        if on_command is not None:
            on_command(normalized, kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return run


def test_frontend_signs_private_copy_then_strictly_verifies_installed_file(tmp_path):
    module = _module()
    project_root, root, native, stamp = _write_frontend_tree(tmp_path)
    commands: list[list[str]] = []

    outcome = module.sign_macos_artifacts(
        project_root=project_root,
        root=root,
        profile="frontend",
        stamp_path=stamp,
        run_command=_successful_runner(commands),
        system_name="Darwin",
    )

    assert outcome.reused is False
    assert outcome.artifact_count == 1
    assert stamp.is_file()
    xattr_commands = [command for command in commands if command[0] == "xattr"]
    sign_commands = [
        command for command in commands if command[0] == "codesign" and "--force" in command
    ]
    verify_commands = [
        command for command in commands if command[0] == "codesign" and "--verify" in command
    ]
    assert len(xattr_commands) == 1
    assert len(sign_commands) == 1
    assert len(verify_commands) == 2
    assert all(Path(command[-1]).name == native.name for command in xattr_commands + sign_commands)
    assert Path(verify_commands[0][-1]).name == native.name
    assert Path(verify_commands[-1][-1]).name == native.name
    assert all("--strict" in command for command in verify_commands)


def test_frontend_skips_javascript_esbuild_wrapper_but_signs_macho_binary(tmp_path):
    module = _module()
    project_root, root, native, stamp = _write_frontend_tree(tmp_path)
    wrapper = root / "esbuild" / "bin" / "esbuild"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text(
        "#!/usr/bin/env node\nrequire('../lib/main').run();\n",
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    outcome = module.sign_macos_artifacts(
        project_root=project_root,
        root=root,
        profile="frontend",
        stamp_path=stamp,
        run_command=_successful_runner(commands),
        system_name="Darwin",
    )

    assert outcome.artifact_count == 1
    assert any(Path(command[-1]).name == native.name for command in commands)
    assert all(Path(command[-1]) != wrapper for command in commands)


def test_frontend_rejects_corrupted_native_candidate_instead_of_shrinking_closure(
    tmp_path,
):
    module = _module()
    project_root, root, native, stamp = _write_frontend_tree(tmp_path)
    native.write_bytes(b"truncated-not-macho")
    commands: list[list[str]] = []

    with pytest.raises(ValueError, match="Mach-O"):
        module.sign_macos_artifacts(
            project_root=project_root,
            root=root,
            profile="frontend",
            stamp_path=stamp,
            run_command=_successful_runner(commands),
            system_name="Darwin",
        )

    assert commands == []
    assert not stamp.exists()


def test_frontend_cache_reuse_still_strictly_verifies_current_closure(tmp_path):
    module = _module()
    project_root, root, native, stamp = _write_frontend_tree(tmp_path)
    module.sign_macos_artifacts(
        project_root=project_root,
        root=root,
        profile="frontend",
        stamp_path=stamp,
        run_command=_successful_runner([]),
        system_name="Darwin",
    )
    commands: list[list[str]] = []

    outcome = module.sign_macos_artifacts(
        project_root=project_root,
        root=root,
        profile="frontend",
        stamp_path=stamp,
        run_command=_successful_runner(commands),
        system_name="Darwin",
    )

    assert outcome.reused is True
    assert len(commands) == 1
    assert commands[0][:-1] == [
        "codesign",
        "--verify",
        "--strict",
        "--verbose=2",
    ]
    assert Path(commands[0][-1]).name == native.name


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX inherited directory fds")
def test_cached_verify_is_fd_bound_during_artifact_root_swap(tmp_path):
    module = _module()
    project_root, root, native, stamp = _write_frontend_tree(tmp_path)
    module.sign_macos_artifacts(
        project_root=project_root,
        root=root,
        profile="frontend",
        stamp_path=stamp,
        run_command=_successful_runner([]),
        system_name="Darwin",
    )
    expected_native = native.read_bytes()
    moved_root = root.with_name("node_modules-moved-cached")
    external_root = tmp_path / "external-node-modules-cached"
    external_native = external_root / native.relative_to(root)
    external_native.parent.mkdir(parents=True)
    external_native.write_bytes(b"EXTERNAL-CACHED-SENTINEL")
    observed: dict[str, object] = {}

    def attack(command, **kwargs):
        normalized = [str(part) for part in command]
        if normalized[0] == "codesign" and "--verify" in normalized:
            root.rename(moved_root)
            root.symlink_to(external_root, target_is_directory=True)
            directory_fd = kwargs.get("working_directory_fd")
            observed["directory_fd"] = directory_fd
            descriptor = os.open(normalized[-1], os.O_RDONLY, dir_fd=directory_fd)
            try:
                observed["verified_bytes"] = os.read(descriptor, 4096)
            finally:
                os.close(descriptor)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises((RuntimeError, ValueError), match="changed|identity|root|link"):
        module.sign_macos_artifacts(
            project_root=project_root,
            root=root,
            profile="frontend",
            stamp_path=stamp,
            run_command=attack,
            system_name="Darwin",
        )

    assert observed["directory_fd"] is not None
    assert observed["verified_bytes"] == expected_native
    assert external_native.read_bytes() == b"EXTERNAL-CACHED-SENTINEL"
    assert not (moved_root / stamp.name).exists()


def test_frontend_native_hardlink_is_rejected_before_external_side_effect(tmp_path):
    module = _module()
    project_root, root, native, stamp = _write_frontend_tree(tmp_path)
    outside = tmp_path / "outside.node"
    outside.write_bytes(MACHO_64_MAGIC + b"outside-sentinel")
    native.unlink()
    os.link(outside, native)
    commands: list[list[str]] = []

    with pytest.raises(ValueError, match="hard link"):
        module.sign_macos_artifacts(
            project_root=project_root,
            root=root,
            profile="frontend",
            stamp_path=stamp,
            run_command=_successful_runner(commands),
            system_name="Darwin",
        )

    assert commands == []
    assert outside.read_bytes() == MACHO_64_MAGIC + b"outside-sentinel"
    assert not stamp.exists()


def test_source_swap_during_codesign_never_mutates_external_hardlink(tmp_path):
    module = _module()
    project_root, root, native, stamp = _write_frontend_tree(tmp_path)
    outside = tmp_path / "outside.node"
    outside.write_bytes(b"outside-sentinel")
    commands: list[list[str]] = []
    swapped = False

    def attack(command: list[str], kwargs) -> None:
        nonlocal swapped
        if command[0] == "codesign" and "--force" in command and not swapped:
            swapped = True
            native.unlink()
            os.link(outside, native)
            descriptor = os.open(
                command[-1],
                os.O_WRONLY | os.O_TRUNC,
                dir_fd=kwargs.get("working_directory_fd"),
            )
            try:
                os.write(descriptor, b"signed-private-copy")
            finally:
                os.close(descriptor)

    with pytest.raises((RuntimeError, ValueError), match="changed|hard link"):
        module.sign_macos_artifacts(
            project_root=project_root,
            root=root,
            profile="frontend",
            stamp_path=stamp,
            run_command=_successful_runner(commands, on_command=attack),
            system_name="Darwin",
        )

    assert outside.read_bytes() == b"outside-sentinel"
    assert not stamp.exists()


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX inherited directory fds")
def test_staging_command_is_fd_bound_during_artifact_root_swap(tmp_path):
    module = _module()
    project_root, root, _native, stamp = _write_frontend_tree(tmp_path)
    moved_root = root.with_name("node_modules-moved")
    external_root = tmp_path / "external-node-modules"
    external_root.mkdir()
    observed = {"directory_fd": None, "external_target": None}

    def attack(command, **kwargs):
        normalized = [str(part) for part in command]
        if normalized[0] == "xattr" and observed["external_target"] is None:
            staged_argument = Path(normalized[-1])
            if staged_argument.is_absolute():
                relative_stage = staged_argument.relative_to(root)
            else:
                staged_matches = list(
                    root.glob(
                        f"{module.STAGING_PREFIX}*/**/{staged_argument.name}"
                    )
                )
                assert len(staged_matches) == 1
                relative_stage = staged_matches[0].relative_to(root)
            root.rename(moved_root)
            external_target = external_root / relative_stage
            external_target.parent.mkdir(parents=True)
            external_target.write_bytes(b"external-sentinel")
            root.symlink_to(external_root, target_is_directory=True)
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
        module.sign_macos_artifacts(
            project_root=project_root,
            root=root,
            profile="frontend",
            stamp_path=stamp,
            run_command=attack,
            system_name="Darwin",
        )

    assert observed["directory_fd"] is not None
    assert observed["external_target"].read_bytes() == b"external-sentinel"
    assert not list(moved_root.glob(".vantage-codesign-staging-*"))
    assert not (moved_root / stamp.name).exists()


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX inherited directory fds")
def test_installed_verify_is_fd_bound_during_artifact_root_swap(tmp_path):
    module = _module()
    project_root, root, native, stamp = _write_frontend_tree(tmp_path)
    expected_native = native.read_bytes()
    moved_root = root.with_name("node_modules-moved-installed")
    external_root = tmp_path / "external-node-modules-installed"
    external_native = external_root / native.relative_to(root)
    external_native.parent.mkdir(parents=True)
    external_native.write_bytes(b"EXTERNAL-INSTALLED-SENTINEL")
    observed: dict[str, object] = {}
    verify_count = 0

    def attack(command, **kwargs):
        nonlocal verify_count
        normalized = [str(part) for part in command]
        if normalized[0] == "codesign" and "--verify" in normalized:
            verify_count += 1
            if verify_count == 2:
                root.rename(moved_root)
                root.symlink_to(external_root, target_is_directory=True)
                directory_fd = kwargs.get("working_directory_fd")
                observed["directory_fd"] = directory_fd
                descriptor = os.open(normalized[-1], os.O_RDONLY, dir_fd=directory_fd)
                try:
                    observed["verified_bytes"] = os.read(descriptor, 4096)
                finally:
                    os.close(descriptor)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises((RuntimeError, ValueError), match="changed|identity|root|link"):
        module.sign_macos_artifacts(
            project_root=project_root,
            root=root,
            profile="frontend",
            stamp_path=stamp,
            run_command=attack,
            system_name="Darwin",
        )

    assert verify_count == 2
    assert observed["directory_fd"] is not None
    assert observed["verified_bytes"] == expected_native
    assert external_native.read_bytes() == b"EXTERNAL-INSTALLED-SENTINEL"
    assert not list(moved_root.glob(f"{module.STAGING_PREFIX}*"))
    assert not (moved_root / stamp.name).exists()


@pytest.mark.parametrize("failure", ["returncode", "timeout"])
def test_codesign_failure_or_timeout_never_writes_frontend_stamp(tmp_path, failure):
    module = _module()
    project_root, root, _native, stamp = _write_frontend_tree(tmp_path)

    def fail(command, **_kwargs):
        if command[0] == "codesign" and "--force" in command:
            if failure == "timeout":
                raise subprocess.TimeoutExpired(command, 0.01)
            return SimpleNamespace(
                returncode=1,
                stdout="NPM_TOKEN=secret ghp_example /Users/private/Vantage",
                stderr="npm :_authToken=hidden password=hunter2 client_secret=value",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises(RuntimeError) as exc_info:
        module.sign_macos_artifacts(
            project_root=project_root,
            root=root,
            profile="frontend",
            stamp_path=stamp,
            run_command=fail,
            system_name="Darwin",
        )

    message = str(exc_info.value)
    assert "NPM_TOKEN=secret" not in message
    assert "ghp_example" not in message
    assert "hidden" not in message
    assert "hunter2" not in message
    assert "client_secret=value" not in message
    assert str(project_root) not in message
    assert not stamp.exists()


def test_cli_failure_is_bounded_redacted_and_has_no_traceback(
    tmp_path,
    monkeypatch,
    capsys,
):
    module = _module()
    project_root, root, _native, stamp = _write_frontend_tree(tmp_path)
    secret = "NPM_TOKEN=secret ghp_example password=hunter2"

    def fail(**_kwargs):
        raise RuntimeError(f"failed below {project_root}: {secret} " + "X" * 65536)

    monkeypatch.setattr(module, "sign_macos_artifacts", fail)

    result = module.main(
        [
            "--project-root",
            str(project_root),
            "--root",
            str(root),
            "--profile",
            "frontend",
            "--stamp",
            str(stamp),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert str(project_root) not in captured.err
    assert "NPM_TOKEN=secret" not in captured.err
    assert "ghp_example" not in captured.err
    assert "hunter2" not in captured.err
    assert "<PROJECT_ROOT>" in captured.err
    assert "output truncated" in captured.err
    assert len(captured.err.encode("utf-8")) <= 16 * 1024


def test_new_native_file_during_signing_invalidates_closure_and_stamp(tmp_path):
    module = _module()
    project_root, root, _native, stamp = _write_frontend_tree(tmp_path)
    added = root / "sample" / "late.node"

    def add_file(command: list[str], _kwargs) -> None:
        if command[0] == "codesign" and "--force" in command and not added.exists():
            added.write_bytes(MACHO_64_MAGIC + b"late")

    with pytest.raises(RuntimeError, match="closure changed"):
        module.sign_macos_artifacts(
            project_root=project_root,
            root=root,
            profile="frontend",
            stamp_path=stamp,
            run_command=_successful_runner([], on_command=add_file),
            system_name="Darwin",
        )

    assert not stamp.exists()


def test_native_change_after_stamp_replace_is_detected_and_stamp_removed(
    tmp_path,
    monkeypatch,
):
    module = _module()
    project_root, root, native, stamp = _write_frontend_tree(tmp_path)
    real_write = module.write_macos_backend_codesign_state

    def write_then_tamper(stamp_path, state, **kwargs):
        result = real_write(stamp_path, state, **kwargs)
        native.write_bytes(MACHO_64_MAGIC + b"tampered-after-stamp")
        return result

    monkeypatch.setattr(module, "write_macos_backend_codesign_state", write_then_tamper)

    with pytest.raises(RuntimeError, match="closure changed"):
        module.sign_macos_artifacts(
            project_root=project_root,
            root=root,
            profile="frontend",
            stamp_path=stamp,
            run_command=_successful_runner([]),
            system_name="Darwin",
        )

    assert not stamp.exists()


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX dirfd replacement")
def test_frontend_root_swap_during_stamp_write_preserves_external_and_cleans_stage(
    tmp_path,
    monkeypatch,
):
    module = _module()
    project_root, root, _native, stamp = _write_frontend_tree(tmp_path)
    moved_root = root.with_name("node_modules-moved")
    external = tmp_path / "external-node-modules"
    external.mkdir()
    external_stamp = external / stamp.name
    external_stamp.write_bytes(b"DO-NOT-TOUCH")
    real_write = module.write_macos_backend_codesign_state
    swapped = False

    def swap_root_then_write(stamp_path, state, **kwargs):
        nonlocal swapped
        if not swapped:
            swapped = True
            root.rename(moved_root)
            root.symlink_to(external, target_is_directory=True)
        return real_write(stamp_path, state, **kwargs)

    monkeypatch.setattr(module, "write_macos_backend_codesign_state", swap_root_then_write)

    with pytest.raises((RuntimeError, ValueError), match="root|link|identity"):
        module.sign_macos_artifacts(
            project_root=project_root,
            root=root,
            profile="frontend",
            stamp_path=stamp,
            run_command=_successful_runner([]),
            system_name="Darwin",
        )

    assert swapped is True
    assert external_stamp.read_bytes() == b"DO-NOT-TOUCH"
    assert not list(moved_root.glob(".vantage-codesign-staging-*"))
    assert not (moved_root / stamp.name).exists()


def test_backend_bundle_profile_is_strict_and_does_not_require_stamp(tmp_path):
    module = _module()
    project_root = tmp_path
    root = project_root / "build" / "backend-runtime" / "stage" / "VantageBackend"
    native = root / "lib" / "sample.so"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"bundle-native")
    commands: list[list[str]] = []

    outcome = module.sign_macos_artifacts(
        project_root=project_root,
        root=root,
        profile="backend-bundle",
        run_command=_successful_runner(commands),
        system_name="Darwin",
    )

    assert outcome.artifact_count == 1
    assert any("--force" in command for command in commands)
    assert any(
        "--verify" in command and Path(command[-1]).name == native.name
        for command in commands
    )
    assert not list(root.glob("*.sha256"))


def test_backend_bundle_preserves_internal_symlink_and_signs_target_once(tmp_path):
    module = _module()
    project_root = tmp_path
    root = project_root / "build" / "backend-runtime" / "stage" / "VantageBackend"
    target = root / "lib" / "payload.bin"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"bundle-native")
    first_link = root / "lib" / "sample.so"
    second_link = root / "lib" / "duplicate.dylib"
    try:
        first_link.symlink_to(target.name)
        second_link.symlink_to(target.name)
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")
    commands: list[list[str]] = []

    module.sign_macos_artifacts(
        project_root=project_root,
        root=root,
        profile="backend-bundle",
        run_command=_successful_runner(commands),
        system_name="Darwin",
    )

    sign_commands = [command for command in commands if "--force" in command]
    verify_commands = [command for command in commands if "--verify" in command]
    installed_verify = verify_commands[-1:]
    assert len(sign_commands) == 1
    assert len(installed_verify) == 1
    assert installed_verify[0][:-1] == [
        "codesign",
        "--verify",
        "--strict",
        "--verbose=2",
    ]
    assert Path(installed_verify[0][-1]).name == target.name
    assert first_link.is_symlink()
    assert second_link.is_symlink()
    assert first_link.resolve() == target
    assert second_link.resolve() == target


def test_backend_bundle_rejects_external_symlink_before_codesign(tmp_path):
    module = _module()
    project_root = tmp_path
    root = project_root / "build" / "backend-runtime" / "stage" / "VantageBackend"
    root.mkdir(parents=True)
    outside = tmp_path / "outside.so"
    outside.write_bytes(b"outside-sentinel")
    link = root / "external.so"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")
    commands: list[list[str]] = []

    with pytest.raises(ValueError, match="escaped|external"):
        module.sign_macos_artifacts(
            project_root=project_root,
            root=root,
            profile="backend-bundle",
            run_command=_successful_runner(commands),
            system_name="Darwin",
        )

    assert commands == []
    assert outside.read_bytes() == b"outside-sentinel"


def test_backend_internal_link_swap_to_external_during_signing_is_rejected(tmp_path):
    module = _module()
    project_root = tmp_path
    root = project_root / "build" / "backend-runtime" / "stage" / "VantageBackend"
    target = root / "lib" / "payload.bin"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"bundle-native")
    link = root / "lib" / "sample.so"
    outside = tmp_path / "outside.so"
    outside.write_bytes(b"outside-sentinel")
    try:
        link.symlink_to(target.name)
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")
    commands: list[list[str]] = []
    swapped = False

    def swap_link(command: list[str], _kwargs) -> None:
        nonlocal swapped
        if command[0] == "codesign" and "--force" in command and not swapped:
            swapped = True
            link.unlink()
            link.symlink_to(outside)

    with pytest.raises((RuntimeError, ValueError), match="link|external|escaped"):
        module.sign_macos_artifacts(
            project_root=project_root,
            root=root,
            profile="backend-bundle",
            run_command=_successful_runner(commands, on_command=swap_link),
            system_name="Darwin",
        )

    assert outside.read_bytes() == b"outside-sentinel"
    assert all(Path(command[-1]) != outside for command in commands)


def test_frontend_stamp_hardlink_is_rejected_without_changing_external_file(tmp_path):
    module = _module()
    project_root, root, _native, stamp = _write_frontend_tree(tmp_path)
    outside = tmp_path / "outside-stamp.json"
    outside.write_text('{"external": true}\n', encoding="utf-8")
    os.link(outside, stamp)

    with pytest.raises(ValueError, match="hard link"):
        module.sign_macos_artifacts(
            project_root=project_root,
            root=root,
            profile="frontend",
            stamp_path=stamp,
            run_command=_successful_runner([]),
            system_name="Darwin",
        )

    assert outside.read_text(encoding="utf-8") == '{"external": true}\n'


def test_profile_root_cannot_be_redirected_outside_project(tmp_path):
    module = _module()
    project_root, _root, _native, stamp = _write_frontend_tree(tmp_path)
    outside = tmp_path / "outside-root"
    outside.mkdir()

    with pytest.raises(ValueError, match="expected root"):
        module.sign_macos_artifacts(
            project_root=project_root,
            root=outside,
            profile="frontend",
            stamp_path=stamp,
            run_command=_successful_runner([]),
            system_name="Darwin",
        )

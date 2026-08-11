from pathlib import Path
import os
import subprocess
import sys
import time

import psutil
import pytest


def _module():
    from src.utils import subprocess_safety

    return subprocess_safety


def _parent_with_pipe_inheriting_descendant(
    pid_path: Path,
    *,
    parent_sleep_seconds: float = 5,
    descendant_sleep_seconds: float = 5,
) -> list[str]:
    descendant = (
        "import time; print('descendant-ready', flush=True); "
        f"time.sleep({descendant_sleep_seconds!r})"
    )
    parent = (
        "import pathlib, subprocess, sys, time; "
        f"child=subprocess.Popen([sys.executable, '-c', {descendant!r}]); "
        f"pathlib.Path({str(pid_path)!r}).write_text(str(child.pid), encoding='utf-8'); "
        "print('parent-ready', flush=True); "
        f"time.sleep({parent_sleep_seconds!r})"
    )
    return [sys.executable, "-c", parent]


def _assert_process_tree_member_stops(pid: int) -> None:
    try:
        process = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    try:
        process.wait(timeout=3)
    except psutil.NoSuchProcess:
        return
    assert not process.is_running() or process.status() == psutil.STATUS_ZOMBIE


def test_real_subprocess_capture_is_bounded_while_both_pipes_are_drained():
    module = _module()
    payload_bytes = module.DEFAULT_SUBPROCESS_OUTPUT_LIMIT_BYTES * 4
    result = module.run_bounded_subprocess(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                f"sys.stdout.write('o' * {payload_bytes}); "
                f"sys.stderr.write('e' * {payload_bytes})"
            ),
        ],
        timeout_seconds=5,
    )

    assert result.returncode == 0
    assert len(result.stdout.encode("utf-8")) <= module.DEFAULT_SUBPROCESS_OUTPUT_LIMIT_BYTES
    assert len(result.stderr.encode("utf-8")) <= module.DEFAULT_SUBPROCESS_OUTPUT_LIMIT_BYTES
    assert "output truncated" in result.stdout
    assert "output truncated" in result.stderr


@pytest.mark.parametrize(
    ("credential_prefix", "secret_tail"),
    [
        ("Authorization: Bearer ", "BEARER_SECRET_TAIL"),
        ("Authorization: Basic ", "BASIC_SECRET_TAIL"),
        ("NPM_TOKEN=", "NPM_SECRET_TAIL"),
    ],
)
def test_fake_subprocess_output_is_redacted_before_truncation_splits_credential(
    credential_prefix,
    secret_tail,
):
    module = _module()
    output_limit = 96
    prefix_limit = (output_limit - len(module._TRUNCATION_MARKER)) // 2
    secret = "s" * 80 + secret_tail
    payload = (
        "p" * max(0, prefix_limit - len(credential_prefix) // 2)
        + credential_prefix
        + secret
    )

    def fail(command, **_kwargs):
        return subprocess.CompletedProcess(command, 1, "", payload)

    result = module.run_bounded_subprocess(
        ["probe"],
        run_command=fail,
        output_limit_bytes=output_limit,
    )

    assert secret_tail not in result.stderr
    assert "[REDACTED_" in result.stderr
    assert len(result.stderr.encode("utf-8")) <= output_limit


def test_real_subprocess_output_is_redacted_before_truncation_splits_bearer():
    module = _module()
    output_limit = 96
    prefix_limit = (output_limit - len(module._TRUNCATION_MARKER)) // 2
    secret_tail = "REAL_BEARER_SECRET_TAIL"
    secret = "s" * 80 + secret_tail
    credential_prefix = "Authorization: Bearer "
    payload = (
        "p" * max(0, prefix_limit - len(credential_prefix) // 2)
        + credential_prefix
        + secret
    )

    result = module.run_bounded_subprocess(
        [
            sys.executable,
            "-c",
            f"import sys; sys.stderr.write({payload!r})",
        ],
        timeout_seconds=5,
        output_limit_bytes=output_limit,
    )

    assert secret_tail not in result.stderr
    assert "[REDACTED_TOKEN]" in result.stderr
    assert len(result.stderr.encode("utf-8")) <= output_limit


@pytest.mark.parametrize(
    ("credential_prefix", "credential_suffix", "secret_marker", "replacement"),
    [
        (
            "https://alice:",
            "@example.test/private",
            "URL_PASSWORD_LEAK",
            "[REDACTED_USERINFO]",
        ),
        (
            '{"NPM_TOKEN":"',
            '"}',
            "JSON_TOKEN_LEAK",
            "[REDACTED_TOKEN]",
        ),
        (
            '{"password":"',
            '"}',
            "JSON_PASSWORD_LEAK",
            "[REDACTED_SECRET]",
        ),
    ],
)
def test_real_subprocess_truncation_redacts_incomplete_credential(
    credential_prefix,
    credential_suffix,
    secret_marker,
    replacement,
):
    module = _module()
    output_limit = 96
    password_padding = module._REDACTION_LOOKAHEAD_BYTES + 1024

    result = module.run_bounded_subprocess(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                f"sys.stderr.write({(credential_prefix + secret_marker)!r} + "
                f"'s' * {password_padding} + {credential_suffix!r})"
            ),
        ],
        timeout_seconds=5,
        output_limit_bytes=output_limit,
    )

    assert secret_marker not in result.stderr
    assert replacement in result.stderr
    assert len(result.stderr.encode("utf-8")) <= output_limit


def test_timeout_output_is_redacted_and_bounded_before_propagation():
    module = _module()
    output_limit = 96
    secret_tail = "TIMEOUT_BEARER_SECRET_TAIL"
    payload = "Authorization: Bearer " + "s" * 200 + secret_tail

    def time_out(command, **_kwargs):
        raise subprocess.TimeoutExpired(command, 1, stderr=payload)

    with pytest.raises(subprocess.TimeoutExpired) as exc_info:
        module.run_bounded_subprocess(
            ["probe"],
            run_command=time_out,
            output_limit_bytes=output_limit,
        )

    captured = module._decode_output(exc_info.value.stderr)
    assert secret_tail not in captured
    assert "[REDACTED_TOKEN]" in captured
    assert len(captured.encode("utf-8")) <= output_limit


def test_real_subprocess_timeout_is_enforced_without_waiting_for_child_exit():
    module = _module()
    started = time.monotonic()

    with pytest.raises(subprocess.TimeoutExpired):
        module.run_bounded_subprocess(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            timeout_seconds=0.2,
        )

    assert time.monotonic() - started < 3


def test_real_subprocess_timeout_terminates_pipe_inheriting_descendant(tmp_path):
    module = _module()
    descendant_pid_path = tmp_path / "descendant.pid"
    started = time.monotonic()

    with pytest.raises(subprocess.TimeoutExpired) as exc_info:
        module.run_bounded_subprocess(
            _parent_with_pipe_inheriting_descendant(descendant_pid_path),
            timeout_seconds=0.5,
            output_limit_bytes=1024,
        )

    elapsed = time.monotonic() - started
    assert elapsed < 2.5
    assert descendant_pid_path.exists()
    descendant_pid = int(descendant_pid_path.read_text(encoding="utf-8"))
    _assert_process_tree_member_stops(descendant_pid)
    captured = (exc_info.value.output or b"") + (exc_info.value.stderr or b"")
    assert len(captured) <= 2048
    assert b"parent-ready" in captured
    assert b"descendant-ready" in captured


def test_pipe_drain_timeout_terminates_descendant_after_parent_exits(tmp_path):
    module = _module()
    descendant_pid_path = tmp_path / "early-parent-descendant.pid"
    started = time.monotonic()
    survivor_was_running = False

    try:
        with pytest.raises(subprocess.TimeoutExpired) as exc_info:
            module.run_bounded_subprocess(
                _parent_with_pipe_inheriting_descendant(
                    descendant_pid_path,
                    parent_sleep_seconds=0,
                    descendant_sleep_seconds=30,
                ),
                timeout_seconds=0.5,
                output_limit_bytes=1024,
            )
    finally:
        if descendant_pid_path.exists():
            descendant_pid = int(descendant_pid_path.read_text(encoding="utf-8"))
            try:
                survivor = psutil.Process(descendant_pid)
            except psutil.NoSuchProcess:
                survivor = None
            if survivor is not None and survivor.is_running():
                try:
                    survivor.wait(timeout=1)
                except psutil.TimeoutExpired:
                    survivor_was_running = True
                    survivor.kill()
                    survivor.wait(timeout=3)
                except psutil.NoSuchProcess:
                    pass

    elapsed = time.monotonic() - started
    assert elapsed < 2.5
    assert descendant_pid_path.exists()
    assert survivor_was_running is False
    _assert_process_tree_member_stops(
        int(descendant_pid_path.read_text(encoding="utf-8"))
    )
    captured = (exc_info.value.output or b"") + (exc_info.value.stderr or b"")
    assert b"parent-ready" in captured
    assert b"descendant-ready" in captured


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX inherited directory fds")
def test_working_directory_fd_survives_canonical_ancestor_replacement(tmp_path):
    module = _module()
    root = tmp_path / "root"
    stage = root / "stage"
    stage.mkdir(parents=True)
    private_target = stage / "native.so"
    private_target.write_bytes(b"private")
    directory_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY)
    moved_root = tmp_path / "root-moved"
    external_root = tmp_path / "external"
    external_stage = external_root / "stage"
    external_stage.mkdir(parents=True)
    external_target = external_stage / private_target.name
    external_target.write_bytes(b"external-sentinel")
    root.rename(moved_root)
    root.symlink_to(external_root, target_is_directory=True)

    try:
        result = module.run_bounded_subprocess(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; Path('native.so').write_bytes(b'updated')",
            ],
            timeout_seconds=2,
            working_directory_fd=directory_fd,
        )
    finally:
        os.close(directory_fd)

    assert result.returncode == 0
    assert (moved_root / "stage" / "native.so").read_bytes() == b"updated"
    assert external_target.read_bytes() == b"external-sentinel"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object handoff")
def test_windows_tree_ownership_failure_does_not_start_target(tmp_path, monkeypatch):
    module = _module()
    target_marker = tmp_path / "target-started.txt"
    monkeypatch.setattr(
        module,
        "_assign_windows_kill_on_close_job",
        lambda _process: None,
    )

    with pytest.raises(RuntimeError, match="tree ownership"):
        module.run_bounded_subprocess(
            [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; "
                    f"Path({str(target_marker)!r}).write_text('started')"
                ),
            ],
            timeout_seconds=1,
        )

    assert not target_marker.exists()


def test_failure_detail_redacts_credentials_and_known_local_paths(tmp_path):
    module = _module()
    private_path = tmp_path / "private" / "config.json"
    secret = "sk-1234567890abcdef"
    result = subprocess.CompletedProcess(
        args=["probe"],
        returncode=1,
        stdout="",
        stderr=f"failed at {private_path} with {secret}",
    )

    detail = module.bounded_process_failure_detail(
        result,
        path_prefixes={"<PROJECT_ROOT>": tmp_path},
    )

    assert str(tmp_path) not in detail
    assert secret not in detail
    assert "<PROJECT_ROOT>" in detail
    assert "sk-[REDACTED]" in detail


def test_failure_detail_redacts_common_http_url_and_github_credentials():
    module = _module()
    secrets = {
        "bearer": "bearer-secret-1234567890",
        "basic": "dXNlcjpwYXNzd29yZA==",
        "url_password": "url-password-123456",
        "github": "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
        "token": "query-secret-1234567890",
        "npm": "npm-secret-1234567890",
        "password": "password-secret-1234567890",
        "client": "client-secret-1234567890",
    }
    stderr = (
        f"Authorization: Bearer {secrets['bearer']}\n"
        f"Authorization: Basic {secrets['basic']}\n"
        f"https://alice:{secrets['url_password']}@example.test/private\n"
        f"github={secrets['github']}\n"
        f"request?token={secrets['token']}&safe=1\n"
        f"NPM_TOKEN={secrets['npm']} password={secrets['password']} "
        f"client_secret={secrets['client']}\n"
    )
    result = subprocess.CompletedProcess(
        args=["probe"], returncode=1, stdout="", stderr=stderr
    )

    detail = module.bounded_process_failure_detail(result)

    assert all(secret not in detail for secret in secrets.values())
    assert "Authorization: Bearer [REDACTED_TOKEN]" in detail
    assert "Authorization: Basic [REDACTED_TOKEN]" in detail
    assert "https://[REDACTED_USERINFO]@example.test" in detail
    assert "ghp_[REDACTED]" in detail
    assert "token=[REDACTED_TOKEN]" in detail
    assert "NPM_TOKEN=[REDACTED_TOKEN]" in detail
    assert "password=[REDACTED_SECRET]" in detail
    assert "client_secret=[REDACTED_SECRET]" in detail


def test_bounded_text_emitter_redacts_and_emits_one_truncation_marker(tmp_path):
    module = _module()
    emitter = module.BoundedTextEmitter(
        limit_bytes=256,
        path_prefixes={"<PROJECT_ROOT>": tmp_path},
    )
    secret = "sk-1234567890abcdef"
    chunks = [
        emitter.filter(f"starting {tmp_path} with {secret}\n"),
        *(emitter.filter("x" * 200 + "\n") for _ in range(10)),
    ]
    output = "".join(chunks)

    assert len(output.encode("utf-8")) <= 256
    assert str(tmp_path) not in output
    assert secret not in output
    assert "<PROJECT_ROOT>" in output
    assert output.count("output truncated") == 1

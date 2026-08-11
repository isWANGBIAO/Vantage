from pathlib import Path
import subprocess
import sys
import time

import pytest


def _module():
    from src.utils import subprocess_safety

    return subprocess_safety


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


def test_real_subprocess_timeout_is_enforced_without_waiting_for_child_exit():
    module = _module()
    started = time.monotonic()

    with pytest.raises(subprocess.TimeoutExpired):
        module.run_bounded_subprocess(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            timeout_seconds=0.2,
        )

    assert time.monotonic() - started < 3


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

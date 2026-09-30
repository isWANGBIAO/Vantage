"""Conversation writes cannot overwrite a reset or a newer plan."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.core.config import Config
from src.core.context import (
    ContextConflictError, ContextManager, context_transaction,
    read_context_snapshot, write_context_messages,
)


@pytest.fixture(autouse=True)
def isolated_history(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, 'get_history_dir', staticmethod(lambda: tmp_path))


def test_two_loaded_contexts_reject_lost_update(tmp_path):
    path = tmp_path / 'latest_context.json'
    write_context_messages(path, [])
    first = ContextManager(path)
    second = ContextManager(path)
    first.add_message('user', 'first')
    second.add_message('user', 'second')
    first.save()
    with pytest.raises(ContextConflictError):
        second.save()
    assert read_context_snapshot(path)[0] == [{'role': 'user', 'content': 'first'}]


def test_identical_reset_invalidates_inflight_generation(tmp_path):
    path = tmp_path / 'latest_context.json'
    original = [{'role': 'assistant', 'content': 'plan'}]
    write_context_messages(path, original)
    pending = ContextManager(path)
    write_context_messages(path, original)
    pending.add_message('user', 'stale')
    with pytest.raises(ContextConflictError):
        pending.save()
    assert read_context_snapshot(path)[0] == original


def test_replace_failure_preserves_complete_previous_json(monkeypatch, tmp_path):
    path = tmp_path / 'latest_context.json'
    write_context_messages(path, [{'role': 'user', 'content': 'before'}])
    real_replace = os.replace
    def fail(source, target):
        if Path(target) == path:
            raise OSError('synthetic interrupted replace')
        return real_replace(source, target)
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError):
        write_context_messages(path, [{'role': 'user', 'content': 'after'}])
    assert json.loads(path.read_text())[0]['content'] == 'before'
    assert not list(tmp_path.glob('.latest_context.json.*'))


def test_context_transaction_is_reentrant(tmp_path):
    path = tmp_path / 'latest_context.json'
    with context_transaction(path):
        with context_transaction(path):
            write_context_messages(path, [])
            assert read_context_snapshot(path)[0] == []


def test_context_transaction_excludes_separate_process(tmp_path):
    path = tmp_path / 'latest_context.json'
    script = (
        "import sys; from src.core.context import write_context_messages; "
        "print('ready', flush=True); "
        "write_context_messages(sys.argv[1],[{'role':'user','content':'child'}]); "
        "print('saved', flush=True)"
    )
    with context_transaction(path):
        process = subprocess.Popen([sys.executable, '-c', script, str(path)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            assert process.stdout.readline().strip() == 'ready'
            with pytest.raises(subprocess.TimeoutExpired):
                process.communicate(timeout=0.1)
            assert not path.exists()
        except BaseException:
            process.kill()
            process.communicate()
            raise
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, stderr
    assert 'saved' in stdout
    assert read_context_snapshot(path)[0][0]['content'] == 'child'


def test_base_context_change_alone_invalidates_inflight_chat(tmp_path):
    path = tmp_path / 'latest_context.json'
    write_context_messages(path, [{'role': 'assistant', 'content': 'old plan'}])
    pending = ContextManager(path)
    write_context_messages(tmp_path / 'latest_action_plan_context.json', [{'role': 'assistant', 'content': 'new plan'}])
    pending.add_message('user', 'stale')
    with pytest.raises(ContextConflictError):
        pending.save()


@pytest.mark.parametrize('raw', [b'', b'{"private": "SECRET', b'{}', b'null', b'"SECRET"', b'\xff'])
def test_corrupt_context_fails_closed_and_preserves_original_bytes(tmp_path, raw):
    from src.core.context import ContextReadError
    path = tmp_path / 'latest_context.json'
    path.write_bytes(raw)
    with pytest.raises(ContextReadError) as failure:
        ContextManager(path)
    assert path.read_bytes() == raw
    assert 'SECRET' not in str(failure.value)
    assert str(path) not in str(failure.value)
    assert not (tmp_path / '.context.revision').exists()


def test_missing_context_is_a_new_empty_session(tmp_path):
    path = tmp_path / 'latest_context.json'
    context = ContextManager(path)
    assert context.messages == []
    assert not path.exists()
    context.add_message('user', 'new')
    context.save()
    assert read_context_snapshot(path)[0] == [{'role': 'user', 'content': 'new'}]

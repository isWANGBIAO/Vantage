"""Synthetic streams exercise the actual parser and round retry boundary."""
import io
import json
import sys
import time
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.scripts import run_prompt
from src.services.llm_client import LLMClient, StreamIncompleteError


def _event(content=None, **fields):
    if content is not None:
        fields = {"choices": [{"delta": {"content": content}}], **fields}
    return ("data: " + json.dumps(fields)).encode("utf-8")


DONE = b"data: [DONE]"
STOP = _event(choices=[{"delta": {}, "finish_reason": "stop"}])


def _client_with_streams(streams):
    client = LLMClient.__new__(LLMClient)
    client.providers = [{"route": "synthetic", "headers": {"Authorization": "Bearer synthetic-secret"}}]
    client.model_parameter_config = {}
    responses = iter(streams)
    client._post_with_failover = lambda *args, **kwargs: (
        SimpleNamespace(iter_lines=lambda **kw: iter(next(responses))), "test-model", "synthetic"
    )
    return client


def _parse(client, callback, recorder=None):
    return client._handle_stream(
        {}, time.time(), callback, None, requested_model="test-model",
        requested_route="synthetic", recorder=recorder, call_id="synthetic-call",
    )


@pytest.mark.parametrize("section", ["analysis", "plan"])
def test_retry_with_real_parser_does_not_emit_terminal_error_on_recovery(section):
    client = _client_with_streams([[_event("partial")], [_event("complete"), STOP, DONE]])
    client.chat = lambda messages, **kwargs: _parse(client, kwargs["print_callback"])
    emitted = []
    result, content = run_prompt.run_action_plan_round(
        client=client, messages=[], section=section, model_override=None,
        provider_route=None, service_tier=None, emit_start_before_first_attempt=True,
        emit=emitted.append,
    )
    assert content == "complete"
    assert result["attempts"] == 2
    assert not any("_ERROR:" in line for line in emitted)
    assert emitted.count(f'STREAM_{section.upper()}_START:""') == 2


@pytest.mark.parametrize("section", ["analysis", "plan"])
def test_retry_with_real_parser_emits_final_error_when_exhausted(section):
    client = _client_with_streams([[_event("partial")], [_event("partial again")]])
    client.chat = lambda messages, **kwargs: _parse(client, kwargs["print_callback"])
    emitted = []
    with pytest.raises(StreamIncompleteError):
        run_prompt.run_action_plan_round(
            client=client, messages=[], section=section, model_override=None,
            provider_route=None, service_tier=None, emit_start_before_first_attempt=True,
            emit=emitted.append,
        )
    assert sum("_ERROR:" in line for line in emitted) == 1


@pytest.mark.parametrize("partial,done", [(False, True), (True, True), (True, False)])
def test_explicit_sse_error_is_fatal_and_redacted(partial, done):
    records = ([_event("incomplete answer")] if partial else []) + [
        _event(error={"message": "synthetic failure synthetic-secret", "code": "test_error"})
    ] + ([DONE] if done else [])
    client = _client_with_streams([records])
    recorder = Mock()
    emitted = []
    with pytest.raises(RuntimeError, match="synthetic failure") as result:
        _parse(client, lambda *event: emitted.append(event), recorder)
    assert "synthetic-secret" not in str(result.value)
    assert any(tag == "error" and "synthetic failure" in text for tag, text in emitted)
    assert not any(tag == "done" for tag, _ in emitted)
    assert "synthetic-secret" not in str(emitted)
    recorder.record_request_completed.assert_not_called()
    recorder.record_request_failed.assert_called_once()


@pytest.mark.parametrize("content,thinking", [("", ""), (" \n\t", ""), ("", "reasoning only")])
def test_empty_chat_reply_exits_failed_and_preserves_context(monkeypatch, tmp_path, content, thinking):
    context = tmp_path / "latest_context.json"
    original = json.dumps([{"role": "system", "content": "synthetic system"}])
    context.write_text(original, encoding="utf-8")
    monkeypatch.setattr(run_prompt.Config, "load_env", lambda: None)
    monkeypatch.setattr(run_prompt.Config, "get_history_dir", lambda: tmp_path)
    client = SimpleNamespace(chat=lambda *args, **kwargs: {
        "content": content, "thinking": thinking, "usage": {}, "duration": 0.1,
    })
    monkeypatch.setattr(run_prompt, "LLMClient", lambda: client)
    monkeypatch.setattr(run_prompt, "_get_or_create_context_session_id", lambda *args: "synthetic")
    monkeypatch.setattr(sys, "argv", ["run_prompt.py", "--chat_message=real question", f"--context_file={context}"])
    output = io.StringIO()
    with redirect_stdout(output), pytest.raises(SystemExit) as result:
        run_prompt.main()
    assert result.value.code != 0
    assert 'STREAM_ERROR:' in output.getvalue()
    assert context.read_text(encoding="utf-8") == original


def test_normal_sse_completion_still_records_success():
    client = _client_with_streams([[_event("complete"), STOP, DONE]])
    recorder = Mock()
    result = _parse(client, lambda *_: None, recorder)
    assert result["content"] == "complete"
    recorder.record_request_completed.assert_called_once()
    recorder.record_request_failed.assert_not_called()

"""Chat text stays data at every public/subprocess boundary."""
import asyncio
import sys
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend import chat
from src.scripts import run_prompt


@pytest.mark.parametrize("message", ["", " ", "\n\t", "\u3000"])
def test_blank_http_chat_is_rejected_before_subprocess(monkeypatch, message):
    spawn = Mock(side_effect=AssertionError("must not spawn"))
    monkeypatch.setattr(chat.asyncio, "create_subprocess_exec", spawn)
    app = FastAPI()
    app.include_router(chat.router)
    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={"message": message})
    assert response.status_code == 422
    spawn.assert_not_called()


@pytest.mark.parametrize("message", ["", " \n\t"])
def test_blank_direct_chat_is_rejected_before_loading_context(monkeypatch, message):
    load = Mock(side_effect=AssertionError("must not load data or configuration"))
    monkeypatch.setattr(run_prompt.Config, "load_env", load)
    monkeypatch.setattr(sys, "argv", ["run_prompt.py", f"--chat_message={message}"])
    with pytest.raises(SystemExit) as result:
        run_prompt.main()
    assert result.value.code == 2
    load.assert_not_called()


@pytest.mark.parametrize("message", ["--help", "--model", "hello", "中文🙂", "line 1\nline 2"])
def test_chat_subprocess_keeps_option_like_text_as_one_value(monkeypatch, tmp_path, message):
    captured = []

    def build(args):
        captured.extend(args)
        return [sys.executable, "-c", "pass"], str(tmp_path)

    monkeypatch.setattr(chat._processes, "_build_run_prompt_subprocess", build)
    monkeypatch.setattr(chat, "_get_history_dir", lambda: str(tmp_path))

    async def exercise():
        response = await chat.chat_endpoint(chat.ChatRequest(message=message))
        return [event async for event in response.body_iterator]

    asyncio.run(exercise())
    # Parse with the real argparse grammar rather than assuming shell quoting.
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--chat_message")
    parser.add_argument("--context_file")
    assert parser.parse_args(captured).chat_message == message

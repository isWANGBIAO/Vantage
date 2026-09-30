import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.backend import chat
from src.backend.api_contracts import ChatStreamEvent


@pytest.mark.parametrize(("lines", "exit_code", "completed"), [
    ([b'STREAM_CONTENT:"hello"\n'], 0, True),
    ([b'STREAM_CONTENT:"partial"\n'], 1, False),
    ([b'STREAM_ERROR:"model failure"\n'], 0, False),
    ([b'STREAM_ANALYSIS_ERROR:"model failure"\n'], 0, False),
])
def test_chat_has_explicit_success_only_after_clean_process_exit(monkeypatch, tmp_path, lines, exit_code, completed):
    process = SimpleNamespace(
        stdout=SimpleNamespace(readline=AsyncMock(side_effect=[*lines, b""])),
        stderr=SimpleNamespace(readline=AsyncMock(return_value=b"")),
        returncode=exit_code,
        wait=AsyncMock(return_value=exit_code),
    )
    monkeypatch.setattr(chat.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    monkeypatch.setattr(chat, "_get_history_dir", lambda: str(tmp_path))

    async def exercise():
        response = await chat.chat_endpoint(chat.ChatRequest(message="fixture"))
        return [json.loads(event) async for event in response.body_iterator]

    records = asyncio.run(exercise())
    for record in records:
        ChatStreamEvent.model_validate(record)
    assert any(record.get("done") is True for record in records) is completed
    if completed:
        assert records[-1] == {"done": True}
    process.wait.assert_awaited()

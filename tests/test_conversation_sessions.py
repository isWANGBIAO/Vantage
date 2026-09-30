"""Canonical chat history and shared-client/reset/publication coordination."""
import asyncio
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.backend import chat
from src.core.config import Config
from src.core.context import ContextConflictError, ContextManager, write_context_messages
from src.services.action_plan_store import ActionPlanStore


@pytest.fixture
def history(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, 'get_history_dir', staticmethod(lambda: tmp_path))
    monkeypatch.setattr(chat, '_load_context_session_stats', lambda path: None)
    return tmp_path


def seed(history):
    base = [{'role': 'system', 'content': 'SECRET SYSTEM'},
            {'role': 'user', 'content': 'SECRET ANALYSIS INPUT'},
            {'role': 'assistant', 'content': 'plan reply'}]
    write_context_messages(history / 'latest_action_plan_context.json', base)
    write_context_messages(history / 'latest_context.json', base)
    return base


def test_independent_client_restores_only_visible_history(history):
    base = seed(history)
    write_context_messages(history / 'latest_context.json', base + [
        {'role': 'user', 'content': '[Message timestamp: 2026-09-30 12:00:00]\nMy question'},
        {'role': 'assistant', 'content': 'My answer'}])
    first = asyncio.run(chat.get_chat_context())
    second = asyncio.run(chat.get_chat_context())
    assert first['messages'] == second['messages'] == [
        {'role': 'assistant', 'content': 'plan reply'},
        {'role': 'user', 'content': 'My question'},
        {'role': 'assistant', 'content': 'My answer'}]
    assert 'SECRET' not in json.dumps(first)


def test_same_base_clear_replaces_history_and_changes_revision(history):
    base = seed(history)
    write_context_messages(history / 'latest_context.json', base + [{'role': 'user', 'content': 'old'}])
    before = asyncio.run(chat.get_chat_context())
    after = asyncio.run(chat.reset_chat_context())
    assert before['base_context_version'] == after['base_context_version']
    assert before['context_version'] != after['context_version']
    assert after['messages'] == [{'role': 'assistant', 'content': 'plan reply'}]


def test_mismatched_or_missing_plan_cannot_expose_model_prompts(history):
    seed(history)
    write_context_messages(history / 'latest_context.json', [{'role': 'user', 'content': 'OTHER PRIVATE PROMPT'}])
    assert asyncio.run(chat.get_chat_context())['messages'] == [{'role': 'assistant', 'content': 'plan reply'}]
    (history / 'latest_action_plan_context.json').unlink()
    assert asyncio.run(chat.get_chat_context())['messages'] == []


def test_chat_without_plan_restores_only_chat_session(history):
    write_context_messages(history / 'latest_context.json', [
        {'role': 'system', 'content': 'SECRET'}, {'role': 'user', 'content': 'hello'},
        {'role': 'assistant', 'content': 'world'}])
    (history / 'latest_context_session.json').write_text(json.dumps({'source': 'chat'}))
    assert asyncio.run(chat.get_chat_context())['messages'] == [
        {'role': 'user', 'content': 'hello'}, {'role': 'assistant', 'content': 'world'}]


def test_published_plan_rejects_late_chat_context_save(history):
    seed(history)
    pending_chat = ContextManager(history / 'latest_context.json')
    store = ActionPlanStore(history)
    pending_plan = store.begin()
    pending_plan.output_file.write_text(json.dumps({'date': date.today().isoformat(),
        'analysis': {'body': 'new analysis'}, 'plan': {'body': 'new plan'}}))
    new_base = [{'role': 'assistant', 'content': 'new plan'}]
    for name in ('latest_context.json', 'latest_action_plan_context.json'):
        (pending_plan.directory / name).write_text(json.dumps(new_base))
    store.publish(pending_plan)
    pending_chat.add_message('assistant', 'old answer')
    with pytest.raises(ContextConflictError):
        pending_chat.save()
    assert asyncio.run(chat.get_chat_context())['messages'] == new_base
    store.discard(pending_plan)


def test_chat_requests_read_and_clear_share_session_serialization(monkeypatch, history):
    seed(history)
    created = []
    gates = []
    class Process:
        returncode = None
        def __init__(self, number):
            self.number = number
            self.context = ContextManager(history / 'latest_context.json')
            self.stdout = SimpleNamespace(readline=self.readline)
            self.stderr = SimpleNamespace(readline=AsyncMock(return_value=b''))
            self.read = False
        async def readline(self):
            if self.read:
                return b''
            self.read = True
            await gates[self.number].wait()
            self.context.add_message('user', str(self.number))
            self.context.add_message('assistant', 'answer')
            self.context.save()
            return b'STREAM_CONTENT:"answer"\n'
        async def wait(self):
            self.returncode = 0
            return 0
    async def spawn(*args, **kwargs):
        process = Process(len(created))
        created.append(process)
        return process
    monkeypatch.setattr(chat.asyncio, 'create_subprocess_exec', spawn)
    async def consume(response):
        return [event async for event in response.body_iterator]
    async def exercise():
        gates.extend([asyncio.Event(), asyncio.Event()])
        first = await chat.chat_endpoint(chat.ChatRequest(message='first'))
        second = await chat.chat_endpoint(chat.ChatRequest(message='second'))
        first_task = asyncio.create_task(consume(first))
        await asyncio.sleep(0)
        second_task = asyncio.create_task(consume(second))
        read_task = asyncio.create_task(chat.get_chat_context())
        clear_task = asyncio.create_task(chat.reset_chat_context())
        await asyncio.sleep(0)
        assert len(created) == 1
        assert not read_task.done() and not clear_task.done()
        gates[0].set()
        await first_task
        await asyncio.sleep(0)
        assert len(created) == 2
        gates[1].set()
        await second_task
        read = await read_task
        assert [m['content'] for m in read['messages']] == ['plan reply', '0', 'answer', '1', 'answer']
        cleared = await clear_task
        assert cleared['messages'] == [{'role': 'assistant', 'content': 'plan reply'}]
    asyncio.run(exercise())


@pytest.mark.parametrize('filename', ['latest_context.json', 'latest_action_plan_context.json'])
@pytest.mark.parametrize('raw', [b'', b'{"SECRET PRIVATE PROMPT":', b'{"private": "SECRET"}', b'\xff'])
@pytest.mark.parametrize('method', ['GET', 'DELETE'])
def test_context_api_preserves_corrupt_files_and_returns_safe_error(history, filename, raw, method):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    seed(history)
    (history / filename).write_bytes(raw)
    original = {name: (history / name).read_bytes() for name in
                ('latest_context.json', 'latest_action_plan_context.json', '.context.revision')}
    app = FastAPI()
    app.include_router(chat.router)
    response = TestClient(app).request(method, '/api/v1/chat/context')
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'CONTEXT_UNREADABLE'
    assert 'SECRET' not in response.text
    assert str(history) not in response.text
    for name, contents in original.items():
        assert (history / name).read_bytes() == contents

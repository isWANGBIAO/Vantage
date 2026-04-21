import test from 'node:test';
import assert from 'node:assert/strict';

import {
  CHAT_CONTEXT_BASE_MESSAGE_COUNT_STORAGE_KEY,
  CHAT_CONTEXT_BASE_UPDATED_EVENT,
  CHAT_CONTEXT_VERSION_STORAGE_KEY,
  CHAT_HISTORY_STORAGE_KEY,
  loadStoredChatContextBaseMessageCount,
  reconcileChatHistoryWithBaseVersion,
} from './chatContextState.js';

function createStorage(initialState = {}) {
  const state = new Map(
    Object.entries(initialState).map(([key, value]) => [key, String(value)]),
  );

  return {
    getItem(key) {
      return state.has(key) ? state.get(key) : null;
    },
    setItem(key, value) {
      state.set(key, String(value));
    },
    removeItem(key) {
      state.delete(key);
    },
  };
}

test('reconcileChatHistoryWithBaseVersion clears stale local chat when base version changes', () => {
  const storage = createStorage({
    [CHAT_HISTORY_STORAGE_KEY]: JSON.stringify([{ role: 'user', content: 'old' }]),
    [CHAT_CONTEXT_VERSION_STORAGE_KEY]: 'base-v1',
  });
  const baseMessages = [{ role: 'assistant', content: 'plan result' }];

  const result = reconcileChatHistoryWithBaseVersion({
    storage,
    nextBaseVersion: 'base-v2',
    baseMessages,
  });

  assert.deepEqual(result.messages, baseMessages);
  assert.equal(result.didReset, true);
  assert.equal(storage.getItem(CHAT_HISTORY_STORAGE_KEY), JSON.stringify(baseMessages));
  assert.equal(storage.getItem(CHAT_CONTEXT_VERSION_STORAGE_KEY), 'base-v2');
  assert.equal(storage.getItem(CHAT_CONTEXT_BASE_MESSAGE_COUNT_STORAGE_KEY), '1');
});

test('reconcileChatHistoryWithBaseVersion preserves local chat when base version is unchanged', () => {
  const baseMessages = [{ role: 'assistant', content: 'seed plan' }];
  const storedMessages = [...baseMessages, { role: 'user', content: 'keep me' }];
  const storage = createStorage({
    [CHAT_HISTORY_STORAGE_KEY]: JSON.stringify(storedMessages),
    [CHAT_CONTEXT_VERSION_STORAGE_KEY]: 'base-v1',
  });

  const result = reconcileChatHistoryWithBaseVersion({
    storage,
    nextBaseVersion: 'base-v1',
    baseMessages,
  });

  assert.deepEqual(result.messages, storedMessages);
  assert.equal(result.didReset, false);
  assert.equal(storage.getItem(CHAT_HISTORY_STORAGE_KEY), JSON.stringify(storedMessages));
  assert.equal(storage.getItem(CHAT_CONTEXT_BASE_MESSAGE_COUNT_STORAGE_KEY), '1');
});

test('reconcileChatHistoryWithBaseVersion hydrates base assistant messages when local history is empty', () => {
  const baseMessages = [
    { role: 'assistant', content: 'analysis result' },
    { role: 'assistant', content: 'plan result' },
  ];
  const storage = createStorage({
    [CHAT_CONTEXT_VERSION_STORAGE_KEY]: 'base-v1',
  });

  const result = reconcileChatHistoryWithBaseVersion({
    storage,
    nextBaseVersion: 'base-v1',
    baseMessages,
  });

  assert.deepEqual(result.messages, baseMessages);
  assert.equal(result.didReset, true);
  assert.equal(storage.getItem(CHAT_HISTORY_STORAGE_KEY), JSON.stringify(baseMessages));
  assert.equal(storage.getItem(CHAT_CONTEXT_BASE_MESSAGE_COUNT_STORAGE_KEY), '2');
});

test('reconcileChatHistoryWithBaseVersion resets stale local chat when it no longer starts with the base messages', () => {
  const baseMessages = [{ role: 'assistant', content: 'current plan' }];
  const storage = createStorage({
    [CHAT_HISTORY_STORAGE_KEY]: JSON.stringify([{ role: 'assistant', content: 'old plan' }]),
    [CHAT_CONTEXT_VERSION_STORAGE_KEY]: 'base-v1',
  });

  const result = reconcileChatHistoryWithBaseVersion({
    storage,
    nextBaseVersion: 'base-v1',
    baseMessages,
  });

  assert.deepEqual(result.messages, baseMessages);
  assert.equal(result.didReset, true);
  assert.equal(storage.getItem(CHAT_HISTORY_STORAGE_KEY), JSON.stringify(baseMessages));
  assert.equal(storage.getItem(CHAT_CONTEXT_BASE_MESSAGE_COUNT_STORAGE_KEY), '1');
});

test('reconcileChatHistoryWithBaseVersion unwraps fenced markdown in assistant base messages', () => {
  const baseMessages = [
    { role: 'assistant', content: '```markdown\n# Plan\n\n- Item\n```' },
  ];
  const storage = createStorage({
    [CHAT_CONTEXT_VERSION_STORAGE_KEY]: 'base-v1',
  });

  const result = reconcileChatHistoryWithBaseVersion({
    storage,
    nextBaseVersion: 'base-v2',
    baseMessages,
  });

  assert.deepEqual(result.messages, [{ role: 'assistant', content: '# Plan\n\n- Item' }]);
  assert.equal(
    storage.getItem(CHAT_HISTORY_STORAGE_KEY),
    JSON.stringify([{ role: 'assistant', content: '# Plan\n\n- Item' }]),
  );
  assert.equal(storage.getItem(CHAT_CONTEXT_BASE_MESSAGE_COUNT_STORAGE_KEY), '1');
});

test('loadStoredChatContextBaseMessageCount infers legacy base messages from leading assistant replies', () => {
  const storage = createStorage({
    [CHAT_HISTORY_STORAGE_KEY]: JSON.stringify([
      { role: 'assistant', content: 'Analysis reply' },
      { role: 'assistant', content: 'Plan reply' },
      { role: 'user', content: 'Refine item 1.' },
    ]),
  });

  assert.equal(loadStoredChatContextBaseMessageCount(storage), 2);
});

test('reconcileChatHistoryWithBaseVersion persists base-message count even when it keeps existing chat history', () => {
  const baseMessages = [
    { role: 'assistant', content: 'Analysis reply' },
    { role: 'assistant', content: 'Plan reply' },
  ];
  const storage = createStorage({
    [CHAT_HISTORY_STORAGE_KEY]: JSON.stringify([
      ...baseMessages,
      { role: 'user', content: 'Refine item 1.' },
    ]),
    [CHAT_CONTEXT_VERSION_STORAGE_KEY]: 'v1',
  });

  const reconciled = reconcileChatHistoryWithBaseVersion({
    storage,
    nextBaseVersion: 'v1',
    baseMessages,
  });

  assert.equal(reconciled.didReset, false);
  assert.equal(reconciled.baseMessageCount, 2);
  assert.equal(storage.getItem(CHAT_CONTEXT_BASE_MESSAGE_COUNT_STORAGE_KEY), '2');
});

test('chat context sync exports a stable event name for action plan resets', () => {
  assert.equal(CHAT_CONTEXT_BASE_UPDATED_EVENT, 'chat-context-base-updated');
});

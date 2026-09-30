import test from 'node:test';
import assert from 'node:assert/strict';
import { CHAT_CONTEXT_BASE_UPDATED_EVENT, normalizeBackendChatContext, retainChatPresentation } from './chatContextState.js';

const base = [{ role: 'assistant', content: 'plan reply' }];
const snapshot = (messages = base, revision = 'one') => ({
  base_context_version: 'same-plan', context_version: revision, display_messages: base, messages,
});

test('independent clients restore the complete authoritative visible history', () => {
  const data = snapshot([...base, { role: 'user', content: 'question' }, { role: 'assistant', content: 'answer' }]);
  assert.deepEqual(normalizeBackendChatContext(data).messages, data.messages);
  assert.deepEqual(normalizeBackendChatContext(data), normalizeBackendChatContext(data));
});

test('same-base explicit clear always replaces local conversation', () => {
  let state = normalizeBackendChatContext(snapshot([...base, { role: 'user', content: 'old' }]));
  const oldBaseVersion = state.baseVersion;
  state = normalizeBackendChatContext(snapshot(base, 'reset'));
  assert.equal(state.baseVersion, oldBaseVersion);
  assert.equal(state.contextVersion, 'reset');
  assert.deepEqual(state.messages, base);
});

test('empty backend history stays empty regardless of stale browser storage', () => {
  const previous = globalThis.localStorage;
  globalThis.localStorage = { getItem: () => { throw new Error('must not read browser chat storage'); } };
  try {
    assert.deepEqual(normalizeBackendChatContext({ base_context_version: 'empty', context_version: 'new', display_messages: [], messages: [] }).messages, []);
  } finally { globalThis.localStorage = previous; }
});

test('private role and invalid snapshots are rejected instead of rendered', () => {
  assert.throws(() => normalizeBackendChatContext(snapshot([{ role: 'system', content: 'private' }])), TypeError);
  assert.throws(() => normalizeBackendChatContext({ display_messages: [], messages: [] }), TypeError);
  assert.throws(() => normalizeBackendChatContext({ ...snapshot(), messages: null }), TypeError);
});

test('base assistant markdown is normalized while follow-up code remains intact', () => {
  const fenced = '```markdown\n# Plan\n```';
  const state = normalizeBackendChatContext({ ...snapshot(), display_messages: [{ role: 'assistant', content: fenced }], messages: [{ role: 'assistant', content: fenced }, { role: 'assistant', content: '```js\nhello()\n```' }] });
  assert.equal(state.baseMessages[0].content, '# Plan');
  assert.equal(state.messages[0].content, '# Plan');
  assert.equal(state.messages[1].content, '```js\nhello()\n```');
});

test('chat context event has one stable name', () => {
  assert.equal(CHAT_CONTEXT_BASE_UPDATED_EVENT, 'chat-context-base-updated');
});


test('confirmed current-turn replies retain presentation but stale local messages cannot survive', () => {
  const message = { role: 'assistant', content: 'answer' };
  const previous = [{ ...message, thinking: 'reasoning', stats: { total_tokens: 9 } }, { role: 'user', content: 'stale' }];
  assert.deepEqual(retainChatPresentation([message], previous), [previous[0]]);
  assert.deepEqual(retainChatPresentation([], previous), []);
  assert.deepEqual(retainChatPresentation([{ ...message, content: 'new' }], previous), [{ ...message, content: 'new' }]);
});

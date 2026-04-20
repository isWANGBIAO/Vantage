import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const chatSource = readFileSync(new URL('./ChatInterface.jsx', import.meta.url), 'utf8');

function loadConsumeChatStreamChunk() {
  const start = chatSource.indexOf('function consumeChatStreamChunk');
  const end = chatSource.indexOf('export default function ChatInterface');

  assert.notEqual(start, -1, 'expected consumeChatStreamChunk helper to exist');
  assert.notEqual(end, -1, 'expected ChatInterface component declaration');

  const helperSource = chatSource.slice(start, end);
  const sandbox = { JSON, globalThis: {} };

  vm.runInNewContext(
    `${helperSource.replace(/^export /, '')}\nglobalThis.consumeChatStreamChunk = consumeChatStreamChunk;`,
    sandbox,
  );

  return sandbox.globalThis.consumeChatStreamChunk;
}

test('ChatInterface copy uses readable labels for model and voice flow', () => {
  assert.ok(chatSource.includes('<span>Model</span>'));
  assert.ok(chatSource.includes('Default model'));
  assert.ok(chatSource.includes('Transcribing speech...'));
  assert.ok(chatSource.includes('Speech transcription failed, please retry or type manually.'));
  assert.ok(chatSource.includes('Speech transcription error: '));
  assert.ok(chatSource.includes('Cannot access microphone, please check permissions.'));
  assert.ok(chatSource.includes('Type a message...'));

  const visibleCopyLines = chatSource
    .split('\n')
    .filter((line) =>
      line.includes('setInput(') ||
      line.includes('alert(') ||
      line.includes('<span>') ||
      line.includes('<option value="">'),
    );

  for (const line of visibleCopyLines) {
    assert.equal(
      [...line].some((ch) => ch.charCodeAt(0) > 127),
      false,
      `visible copy line should stay ASCII: ${line}`,
    );
  }
});

test('consumeChatStreamChunk reassembles split NDJSON lines without losing content', () => {
  const consumeChatStreamChunk = loadConsumeChatStreamChunk();
  let state = {
    buffer: '',
    assistantContent: '',
    assistantThinking: '',
    error: null,
  };

  state = consumeChatStreamChunk(state, '{"log":"STREAM_CONTENT:\\"Hel');

  assert.equal(state.assistantContent, '');
  assert.equal(state.assistantThinking, '');
  assert.equal(state.buffer, '{"log":"STREAM_CONTENT:\\"Hel');
  assert.equal(state.error, null);

  state = consumeChatStreamChunk(state, 'lo\\""}\n');

  assert.equal(state.assistantContent, 'Hello');
  assert.equal(state.assistantThinking, '');
  assert.equal(state.buffer, '');
  assert.equal(state.error, null);
});

test('consumeChatStreamChunk surfaces backend errors', () => {
  const consumeChatStreamChunk = loadConsumeChatStreamChunk();
  const state = {
    buffer: '',
    assistantContent: '',
    assistantThinking: '',
    error: null,
  };

  const nextState = consumeChatStreamChunk(state, '{"error":"boom"}\n');

  assert.equal(nextState.error, 'boom');
  assert.equal(nextState.assistantContent, '');
  assert.equal(nextState.assistantThinking, '');
});

test('consumeChatStreamChunk ignores plain Thinking logs', () => {
  const consumeChatStreamChunk = loadConsumeChatStreamChunk();
  const state = {
    buffer: '',
    assistantContent: '',
    assistantThinking: '',
    stats: null,
    error: null,
  };

  const nextState = consumeChatStreamChunk(
    state,
    '{"log":"Thinking..."}\n{"log":"---CHAT_START---"}\n{"log":"STREAM_CONTENT:\\"Hi\\""}\n',
  );

  assert.equal(nextState.assistantContent, 'Hi');
  assert.equal(nextState.assistantThinking, '');
  assert.equal(nextState.error, null);
});

test('consumeChatStreamChunk parses stats payloads without affecting content', () => {
  const consumeChatStreamChunk = loadConsumeChatStreamChunk();
  const state = {
    buffer: '',
    assistantContent: '',
    assistantThinking: '',
    stats: null,
    error: null,
  };

  const nextState = consumeChatStreamChunk(
    state,
    '{"log":"STATS_JSON:{\\"total_tokens\\":128,\\"historical_total_tokens\\":512,\\"speed\\":\\"3.50 tokens/s\\"}"}\n',
  );

  assert.equal(nextState.stats.total_tokens, 128);
  assert.equal(nextState.stats.historical_total_tokens, 512);
  assert.equal(nextState.stats.speed, '3.50 tokens/s');
  assert.equal(nextState.assistantContent, '');
  assert.equal(nextState.assistantThinking, '');
  assert.equal(nextState.error, null);
});

test('ChatInterface syncs visible history with backend chat context endpoints', () => {
  assert.ok(chatSource.includes("fetchBackendJson('/api/chat/context'"));
  assert.ok(chatSource.includes("method: 'DELETE'") || chatSource.includes('method: "DELETE"'));
  assert.ok(chatSource.includes('CHAT_CONTEXT_BASE_UPDATED_EVENT'));
});

test('ChatInterface sends chat timestamps and action-plan reasoning effort to backend', () => {
  assert.ok(chatSource.includes('client_sent_at'));
  assert.ok(chatSource.includes('reasoning_effort'));
  assert.ok(chatSource.includes('loadStoredActionPlanReasoningEffort'));
});

test('ChatInterface renders chat token stats and hydrates them from backend context', () => {
  assert.ok(chatSource.includes('setStats('));
  assert.ok(chatSource.includes('data?.stats'));
  assert.ok(chatSource.includes('Speed {stats.speed}'));
  assert.ok(chatSource.includes('computeDisplayedDurationSeconds'));
  assert.ok(chatSource.includes('Tokens {((stats.total_tokens || 0) / 1000).toFixed(1)}k'));
  assert.ok(chatSource.includes('History {stats.historical_total_tokens >= 1000000'));
});

test('ChatInterface seeds live timing stats as soon as a request starts', () => {
  assert.ok(chatSource.includes('startTime: Date.now()'));
  assert.ok(chatSource.includes('const [liveDurationNowMs, setLiveDurationNowMs] = useState(() => Date.now())'));
});

test('ChatInterface does not hardcode Gemini provider copy and keeps user markdown readable', () => {
  assert.equal(chatSource.includes('Powered by Gemini'), false);
  assert.ok(chatSource.includes('providerLabel'));
  assert.ok(chatSource.includes("isUser ? 'inherit'"));
});

test('ChatInterface replaces unreliable chat icons with text badges and text action buttons', () => {
  assert.ok(chatSource.includes("'AI'"));
  assert.ok(chatSource.includes("'ME'"));
  assert.ok(chatSource.includes("'REC'"));
  assert.ok(chatSource.includes("'STOP'"));
  assert.ok(chatSource.includes("'SEND'"));
  assert.equal(chatSource.includes('<User size={16}'), false);
  assert.equal(chatSource.includes('<Mic size={20}'), false);
  assert.equal(chatSource.includes('<StopCircle size={20}'), false);
  assert.equal(chatSource.includes('<Send size={18}'), false);
});

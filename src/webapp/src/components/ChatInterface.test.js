import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { normalizeBackendChatContext } from '../utils/chatContextState.js';

const chatSource = readFileSync(new URL('./ChatInterface.jsx', import.meta.url), 'utf8');
const displayCopySource = readFileSync(new URL('../utils/displayCopy.js', import.meta.url), 'utf8');

function loadChatHelpers() {
  const start = chatSource.indexOf('function consumeChatStreamChunk');
  const end = chatSource.indexOf('export default function ChatInterface');

  assert.notEqual(start, -1, 'expected consumeChatStreamChunk helper to exist');
  assert.notEqual(end, -1, 'expected ChatInterface component declaration');

  const helperSource = chatSource.slice(start, end);
  const sandbox = { JSON, globalThis: {} };

  vm.runInNewContext(
    `${helperSource.replace(/^export /, '')}
globalThis.consumeChatStreamChunk = consumeChatStreamChunk;
globalThis.getVisibleMessages = getVisibleMessages;`,
    sandbox,
  );

  return {
    consumeChatStreamChunk: sandbox.globalThis.consumeChatStreamChunk,
    getVisibleMessages: sandbox.globalThis.getVisibleMessages,
  };
}

test('ChatInterface copy uses readable labels for model and voice flow', () => {
  assert.ok(chatSource.includes("t('common.model')"));
  assert.ok(chatSource.includes("t('chat.default_model')"));
  assert.ok(chatSource.includes("t('chat.transcribing')"));
  assert.ok(chatSource.includes("t('chat.transcription_failed')"));
  assert.ok(chatSource.includes("t('chat.transcription_error'"));
  assert.ok(chatSource.includes("t('chat.voice_model'"));
  assert.ok(chatSource.includes("t('chat.voice_config_error'"));
  assert.ok(chatSource.includes("t('chat.microphone_error'"));
  assert.ok(chatSource.includes("t('chat.input_placeholder')"));

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

test('ChatInterface loads voice provider settings and surfaces transcription metadata', () => {
  assert.ok(chatSource.includes('loadSettingsState'));
  assert.ok(chatSource.includes('voiceConfig'));
  assert.ok(chatSource.includes('voice_model'));
  assert.ok(chatSource.includes('voice_base_url'));
  assert.ok(chatSource.includes('configuration_error'));
  assert.ok(chatSource.includes("allowHttpError: true"));
  assert.ok(chatSource.includes("vantage:settings-updated"));
});

test('ChatInterface does not log voice transcription payloads to the console', () => {
  assert.ok(!chatSource.includes('Transcribe result'));
  assert.ok(!chatSource.includes('Transcribed text'));
  assert.ok(!chatSource.includes('Starting recording'));
  assert.ok(!chatSource.includes('Audio blob size'));
  assert.ok(!chatSource.includes('Data available'));
});

test('ChatInterface cleans up recording stream and timer when unmounted', () => {
  assert.ok(chatSource.includes('cleanupRecordingResources'));
  assert.ok(chatSource.includes('mediaRecorderRef.current.onstop = null'));
  assert.ok(chatSource.includes('streamRef.current.getTracks().forEach((track) => track.stop())'));
  assert.ok(chatSource.includes('return cleanupRecordingResources;'));
});

test('ChatInterface uses provider-aware model options before falling back to legacy models', () => {
  assert.ok(chatSource.includes('const defaultModel = data?.default_model'));
  assert.ok(chatSource.includes('buildModelOptionsFromCatalog(data)'));
  assert.ok(chatSource.includes('preferred_llm_model_ref'));
  assert.ok(chatSource.includes('payload.provider_route'));
  assert.ok(chatSource.includes("vantage:llm-models-updated"));
});

test('ChatInterface sends fast priority service tier only through supported proxy model helper', () => {
  assert.ok(chatSource.includes('loadStoredFastModeEnabled'));
  assert.ok(chatSource.includes('isFastModeSupportedForModel'));
  assert.ok(chatSource.includes('service_tier'));
  assert.ok(chatSource.includes("t('common.fast_mode')"));
});

test('ChatInterface defaults to the latest Action Plan provider-aware model route', () => {
  assert.ok(chatSource.includes('contextPreferredModelRef'));
  assert.ok(chatSource.includes('data?.preferred_model_option_id'));
  assert.ok(chatSource.includes('buildModelOptionId(data?.preferred_provider_route, data?.preferred_model)'));
  assert.ok(chatSource.includes('findModelOption(modelList, contextPreferredModelRef.current)'));
});

test('ChatInterface warns when the user switches away from the inherited cache route', () => {
  assert.ok(chatSource.includes("t('chat.cache_route_warning')"));
  assert.ok(chatSource.includes('hasCacheRouteWarning'));
  assert.ok(displayCopySource.includes("'chat.cache_route_warning'"));
});

test('consumeChatStreamChunk reassembles split NDJSON lines without losing content', () => {
  const { consumeChatStreamChunk } = loadChatHelpers();
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
  const { consumeChatStreamChunk } = loadChatHelpers();
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
  const { consumeChatStreamChunk } = loadChatHelpers();
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
  const { consumeChatStreamChunk } = loadChatHelpers();
  const state = {
    buffer: '',
    assistantContent: '',
    assistantThinking: '',
    stats: null,
    error: null,
  };

  const nextState = consumeChatStreamChunk(
    state,
    '{"log":"STATS_JSON:{\\"total_tokens\\":128,\\"speed\\":\\"3.50 tokens/s\\"}"}\n',
  );

  assert.equal(nextState.stats.total_tokens, 128);
  assert.equal(nextState.stats.speed, '3.50 tokens/s');
  assert.equal(nextState.assistantContent, '');
  assert.equal(nextState.assistantThinking, '');
  assert.equal(nextState.error, null);
});

test('ChatInterface syncs visible history with backend chat context endpoints', () => {
  assert.ok(chatSource.includes("fetchBackendJson('/api/v1/chat/context'"));
  assert.ok(chatSource.includes("method: 'DELETE'") || chatSource.includes('method: "DELETE"'));
  assert.ok(chatSource.includes('CHAT_CONTEXT_BASE_UPDATED_EVENT'));
});

test('ChatInterface sends chat timestamps and action-plan reasoning effort to backend', () => {
  assert.ok(chatSource.includes('client_sent_at'));
  assert.ok(chatSource.includes('reasoning_effort'));
  assert.ok(chatSource.includes('loadStoredActionPlanReasoningEffort'));
  assert.ok(chatSource.includes('normalizeReasoningEffortForModel'));
});

test('ChatInterface renders chat token stats and hydrates them from backend context', () => {
  assert.ok(chatSource.includes('setStats('));
  assert.ok(chatSource.includes('data?.stats'));
  assert.ok(chatSource.includes("t('common.speed'"));
  assert.ok(chatSource.includes('computeDisplayedDurationSeconds'));
  assert.ok(chatSource.includes("t('common.tokens'"));
  assert.equal(chatSource.includes("t('common.history'"), false);
  assert.equal(chatSource.includes('historical_total_tokens'), false);
});

test('ChatInterface keeps reasoning blocks collapsed until the user expands them', () => {
  assert.ok(chatSource.includes('<details className="thinking-block">'));
  assert.ok(chatSource.includes('<summary className="thinking-header">'));
  assert.equal(chatSource.includes('<details className="thinking-block" open>'), false);
});

test('ChatInterface annotates reasoning titles with the assistant message duration when available', () => {
  assert.ok(chatSource.includes('formatThinkingTitleWithDuration'));
  assert.ok(chatSource.includes('lastMsg.stats = streamState.stats'));
  assert.ok(chatSource.includes('msg.stats?.total_duration ?? msg.stats?.duration'));
  assert.ok(chatSource.includes('msg.stats?.completion_reasoning_tokens'));
});

test('ChatInterface seeds live timing stats as soon as a request starts', () => {
  assert.ok(chatSource.includes('startTime: Date.now()'));
  assert.ok(chatSource.includes('const [liveDurationNowMs, setLiveDurationNowMs] = useState(() => Date.now())'));
});

test('ChatInterface uses dynamic provider copy and keeps user markdown readable', () => {
  assert.ok(chatSource.includes("t('chat.powered_by', { provider: providerLabel })"));
  assert.ok(chatSource.includes("isUser ? 'inherit'"));
});

test('ChatInterface markdown renderers avoid unused node params', () => {
  assert.equal(chatSource.includes('p: ({ node, ...props }) => ('), false);
  assert.equal(chatSource.includes('li: ({ node, ...props }) => ('), false);
  assert.equal(chatSource.includes('strong: ({ node, ...props }) => ('), false);
});

test('ChatInterface replaces unreliable chat icons with text badges and text action buttons', () => {
  assert.ok(chatSource.includes("t('chat.role.assistant')"));
  assert.ok(chatSource.includes("t('chat.role.user')"));
  assert.ok(chatSource.includes("t('chat.record.short_start')"));
  assert.ok(chatSource.includes("t('chat.record.short_stop')"));
  assert.ok(chatSource.includes("t('chat.send_short')"));
  assert.equal(chatSource.includes("'REC'"), false);
  assert.equal(chatSource.includes("'STOP'"), false);
  assert.equal(chatSource.includes("'SEND'"), false);
  assert.equal(chatSource.includes('<User size={16}'), false);
  assert.equal(chatSource.includes('<Mic size={20}'), false);
  assert.equal(chatSource.includes('<StopCircle size={20}'), false);
  assert.equal(chatSource.includes('<Send size={18}'), false);
});

test('ChatInterface supports embedded workspace mode with a separate sticky composer panel', () => {
  assert.ok(chatSource.includes('export default function ChatInterface({ embedded = false } = {})'));
  assert.ok(chatSource.includes("height: embedded ? 'auto' : '100%'"));
  assert.ok(chatSource.includes("overflowY: embedded ? 'visible' : 'auto'"));
  assert.ok(chatSource.includes('const composerPanel = ('));
  assert.ok(chatSource.includes('return embedded ? ('));
  assert.equal(chatSource.includes("position: embedded ? 'sticky' : 'static'"), false);
});

test('embedded chat hides inherited plan replies after backend restore', () => {
  const { getVisibleMessages } = loadChatHelpers();
  const base = [{ role: 'assistant', content: 'analysis' }, { role: 'assistant', content: 'plan' }];
  const tail = [{ role: 'user', content: 'question' }, { role: 'assistant', content: 'answer' }];
  const state = normalizeBackendChatContext({ base_context_version: 'base', context_version: 'turn', display_messages: base, messages: [...base, ...tail] });
  assert.deepEqual(getVisibleMessages({ embedded: true, messages: state.messages, baseMessages: state.baseMessages }), tail);
});

test('chat uses backend history without a stale local-storage fallback', () => {
  assert.ok(chatSource.includes('normalizeBackendChatContext(data)'));
  assert.ok(chatSource.includes("'/api/v1/chat/context'"));
  assert.ok(chatSource.includes('chatAbortControllerRef.current?.abort()'));
  assert.ok(!chatSource.includes('loadStoredChatMessages'));
  assert.ok(!chatSource.includes('saveStoredChatMessages'));
  assert.ok(!chatSource.includes('reconcileChatHistoryWithBaseVersion'));
});

test('actual clear callback replaces follow-up messages with same-base backend response', async () => {
  const start = chatSource.indexOf('    const clearChat = async () => {');
  const end = chatSource.indexOf('    const handleModelChange = ', start);
  assert.ok(start >= 0 && end > start);
  const base = [{ role: 'assistant', content: 'plan reply' }];
  let messages = [...base, { role: 'user', content: 'old question' }];
  let requested;
  const sandbox = {
    isLoading: false,
    window: { confirm: () => true },
    t: (key) => key,
    fetchBackendJson: async (path, options) => {
      requested = { path, options };
      return { base_context_version: 'unchanged', context_version: 'reset', display_messages: base, messages: base };
    },
    contextRequestVersionRef: { current: 1 },
    normalizeBackendChatContext,
    setMessages: (value) => { messages = value; },
    setBaseMessages: () => {}, setContextReady: () => {}, setChatError: () => {}, setStats: () => {},
    console,
    globalThis: {},
  };
  vm.runInNewContext(`${chatSource.slice(start, end)}\nglobalThis.clearChat = clearChat;`, sandbox);
  await sandbox.globalThis.clearChat();
  assert.equal(requested.path, '/api/v1/chat/context');
  assert.equal(requested.options.method, 'DELETE');
  assert.deepEqual(messages, base);
});

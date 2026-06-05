import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createNdjsonLineBuffer,
  createStreamRenderScheduler,
  parseActionPlanStreamLog,
} from './actionPlanStream.js';

test('parseActionPlanStreamLog reads analysis content events', () => {
  assert.deepEqual(
    parseActionPlanStreamLog('STREAM_ANALYSIS_CONTENT:"hello"'),
    {
      section: 'analysis',
      kind: 'content',
      content: 'hello',
    },
  );
});

test('parseActionPlanStreamLog reads plan start events', () => {
  assert.deepEqual(
    parseActionPlanStreamLog('STREAM_PLAN_START:""'),
    {
      section: 'plan',
      kind: 'start',
      content: '',
    },
  );
});

test('parseActionPlanStreamLog reads analysis prompt events', () => {
  assert.deepEqual(
    parseActionPlanStreamLog('STREAM_ANALYSIS_PROMPT:"prompt text"'),
    {
      section: 'analysis',
      kind: 'prompt',
      content: 'prompt text',
    },
  );
});

test('parseActionPlanStreamLog reads plan metadata events', () => {
  assert.deepEqual(
    parseActionPlanStreamLog('STREAM_PLAN_METADATA:{"model":"gemini-3.1-pro-high","provider_route":"cliproxyapi_secondary"}'),
    {
      section: 'plan',
      kind: 'metadata',
      content: {
        model: 'gemini-3.1-pro-high',
        provider_route: 'cliproxyapi_secondary',
      },
    },
  );
});

test('parseActionPlanStreamLog reads analysis system events', () => {
  assert.deepEqual(
    parseActionPlanStreamLog('STREAM_ANALYSIS_SYSTEM:"system text"'),
    {
      section: 'analysis',
      kind: 'system',
      content: 'system text',
    },
  );
});

test('parseActionPlanStreamLog reads plan thinking events', () => {
  assert.deepEqual(
    parseActionPlanStreamLog('STREAM_PLAN_THINKING:"thinking"'),
    {
      section: 'plan',
      kind: 'thinking',
      content: 'thinking',
    },
  );
});

test('parseActionPlanStreamLog ignores unrelated logs', () => {
  assert.equal(parseActionPlanStreamLog('STATS_JSON:{}'), null);
});

test('parseActionPlanStreamLog redacts api keys from streamed errors', () => {
  const secret = '2615cad9be45f50badccd2fa5ffc2bd4596c01eb937c5204388a9c59dfc77b19';

  assert.deepEqual(
    parseActionPlanStreamLog(`STREAM_ANALYSIS_ERROR:"Rate limit exceeded for api_key: ${secret}"`),
    {
      section: 'analysis',
      kind: 'error',
      content: 'Rate limit exceeded for api_key: [REDACTED_API_KEY]',
    },
  );
});

test('createNdjsonLineBuffer preserves split lines across chunks', () => {
  const lineBuffer = createNdjsonLineBuffer();

  assert.deepEqual(
    lineBuffer.push('{"log":"one"}\n{"log":"tw'),
    ['{"log":"one"}'],
  );

  assert.deepEqual(
    lineBuffer.push('o"}\n'),
    ['{"log":"two"}'],
  );

  assert.deepEqual(lineBuffer.flush(), []);
});

test('createNdjsonLineBuffer flushes trailing line without newline', () => {
  const lineBuffer = createNdjsonLineBuffer();

  assert.deepEqual(lineBuffer.push('{"log":"tail"}'), []);
  assert.deepEqual(lineBuffer.flush(), ['{"log":"tail"}']);
});

test('createStreamRenderScheduler yields after each streamed update', async () => {
  const scheduledCallbacks = [];
  const waitForRender = createStreamRenderScheduler({
    schedule: (callback) => {
      scheduledCallbacks.push(callback);
    },
  });

  const pending = waitForRender();
  let resolved = false;
  pending.then(() => {
    resolved = true;
  });

  await Promise.resolve();

  assert.equal(resolved, false);
  assert.equal(scheduledCallbacks.length, 1);

  scheduledCallbacks.shift()();
  await pending;

  assert.equal(resolved, true);
});

test('createStreamRenderScheduler resolves immediately when streaming view is hidden', async () => {
  let scheduledCount = 0;
  const waitForRender = createStreamRenderScheduler({
    shouldYield: () => false,
    schedule: () => {
      scheduledCount += 1;
    },
  });

  await waitForRender();

  assert.equal(scheduledCount, 0);
});

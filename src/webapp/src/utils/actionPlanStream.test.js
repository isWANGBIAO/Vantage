import test from 'node:test';
import assert from 'node:assert/strict';

import { parseActionPlanStreamLog } from './actionPlanStream.js';

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

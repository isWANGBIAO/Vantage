import test from 'node:test';
import assert from 'node:assert/strict';
import { createActionPlanRevisionChecker, consumeActionPlanCompletion } from './actionPlanAutoRefresh.js';

test('revision checks baseline, unchanged, updated and retry failed generation', async () => {
  const check = createActionPlanRevisionChecker();
  let revision = 'a';
  let fail = false;
  let generations = 0;
  const args = { getRevision: async () => revision, generate: async () => {
    generations += 1;
    if (fail) throw new Error('failed');
  } };
  assert.equal(await check(args), 'baseline');
  assert.equal(await check(args), 'unchanged');
  revision = 'b'; fail = true;
  await assert.rejects(check(args), /failed/);
  fail = false;
  assert.equal(await check(args), 'updated');
  assert.equal(generations, 2);
  assert.equal(await check(args), 'unchanged');
});

test('revision checker prevents overlap and skips active manual generation', async () => {
  const check = createActionPlanRevisionChecker();
  let release;
  const pending = check({ getRevision: () => new Promise((resolve) => { release = resolve; }) });
  assert.equal(await check({}), 'busy');
  release('a'); await pending;
  assert.equal(await check({ isGenerating: () => true }), 'busy');
});

function response(lines) {
  return new Response(lines.map((line) => JSON.stringify(line)).join('\n'));
}

test('completion requires explicit success, rejects EOF and error even after done', async () => {
  await consumeActionPlanCompletion(response([{ log: 'output' }, { done: true }]));
  await assert.rejects(consumeActionPlanCompletion(response([{ log: 'output' }])), /before successful completion/);
  await assert.rejects(consumeActionPlanCompletion(response([{ done: true }, { error: 'failed' }])), /failed/);
});

test('failed source lookup preserves baseline for retry', async () => {
  const check = createActionPlanRevisionChecker();
  await check({ getRevision: async () => 'a' });
  await assert.rejects(check({ getRevision: async () => { throw new Error('offline'); } }), /offline/);
  let generated = false;
  assert.equal(await check({ getRevision: async () => 'b', generate: async () => { generated = true; } }), 'updated');
  assert.equal(generated, true);
});

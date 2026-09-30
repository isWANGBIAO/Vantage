import test from 'node:test';
import assert from 'node:assert/strict';
import {
  ACTION_PLAN_JOBS_PATH,
  createActionPlanJobMonitor,
  getActionPlanJobError,
  getCompletedActionPlanJobResult,
  isActiveActionPlanJob,
  isBackgroundActionPlanJob,
  isActionPlanJobResultCurrent,
  readActionPlanJobEvents,
} from './actionPlanJobs.js';

const completeResult = { exists: true, analysis: { body: 'Analysis' }, plan: { body: 'Plan' }, meta: {} };
const runningJob = { id: 'job-1', status: 'running', trigger: 'manual', event_cursor: 0 };
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const response = (events) => new Response(events.map((event) => JSON.stringify(event)).join('\n'));

function deferred() {
  let resolve;
  const promise = new Promise((accept) => { resolve = accept; });
  return { promise, resolve };
}

function fixture(overrides = {}) {
  const snapshots = [];
  const events = [];
  const errors = [];
  const requests = [];
  const timers = [];
  let cancelCount = 0;
  const monitor = createActionPlanJobMonitor({
    onSnapshot: (snapshot) => snapshots.push(snapshot),
    onEvent: (event) => events.push(event),
    onObservationError: (error) => errors.push(error),
    fetchJson: async (path, options) => {
      requests.push({ path, options });
      return path === ACTION_PLAN_JOBS_PATH ? { jobs: [], active: null } : runningJob;
    },
    fetchStream: async () => new Response(new ReadableStream({ cancel() { cancelCount += 1; } })),
    schedule: (callback, delay) => { const timer = { callback, delay }; timers.push(timer); return timer; },
    cancelSchedule: (timer) => { timer.cancelled = true; },
    ...overrides,
  });
  return { monitor, snapshots, events, errors, requests, timers, cancelledReaders: () => cancelCount };
}

test('only a succeeded snapshot containing both nonblank rounds is complete', () => {
  assert.equal(getCompletedActionPlanJobResult({ status: 'succeeded', result: completeResult }), completeResult);
  for (const status of ['queued', 'running', 'cancelling', 'failed', 'cancelled']) {
    assert.equal(getCompletedActionPlanJobResult({ status, result: completeResult }), null);
  }
  for (const result of [null, {}, { ...completeResult, exists: false }, { ...completeResult, error: 'failed' },
    { ...completeResult, plan: { body: ' ' } }, { ...completeResult, analysis: {} }]) {
    assert.equal(getCompletedActionPlanJobResult({ status: 'succeeded', result }), null);
  }
});

test('active and background jobs follow the server status and trigger contracts', () => {
  for (const status of ['queued', 'running', 'cancelling']) assert.equal(isActiveActionPlanJob({ status }), true);
  for (const status of ['succeeded', 'failed', 'cancelled']) assert.equal(isActiveActionPlanJob({ status }), false);
  assert.equal(isBackgroundActionPlanJob({ trigger: 'manual' }), false);
  for (const trigger of ['startup', 'source_changed', 'future_backend_trigger']) {
    assert.equal(isBackgroundActionPlanJob({ trigger }), true);
  }
  assert.equal(getActionPlanJobError({ code: 'generation_failed', message: 'Provider failed' }), 'Provider failed');
  assert.equal(getActionPlanJobError('Stream failed'), 'Stream failed');
});

test('event reader accepts split NDJSON, resumes by sequence and suppresses duplicates', async () => {
  const payload = [
    { sequence: 1, log: 'old' },
    { sequence: 2, log: 'STREAM_ANALYSIS_CONTENT:"新内容"' },
    { sequence: 2, log: 'duplicate' },
    { sequence: 3, done: true },
  ].map((event) => JSON.stringify(event)).join('\r\n');
  const bytes = new TextEncoder().encode(payload);
  const stream = new ReadableStream({
    start(controller) {
      for (let offset = 0; offset < bytes.length; offset += 3) controller.enqueue(bytes.slice(offset, offset + 3));
      controller.close();
    },
  });
  const events = [];
  const cursors = [];
  const outcome = await readActionPlanJobEvents(new Response(stream), {
    after: 1, onEvent: (event) => events.push(event), onCursor: (cursor) => cursors.push(cursor),
  });
  assert.deepEqual(events.map((event) => event.sequence), [2, 3]);
  assert.match(events[0].log, /新内容/);
  assert.deepEqual(cursors, [2, 3]);
  assert.deepEqual(outcome, { cursor: 3, done: true, truncated: false });
});

test('EOF never invents a done event or a successful result', async () => {
  assert.deepEqual(await readActionPlanJobEvents(response([{ sequence: 1, log: 'partial' }])), {
    cursor: 1, done: false, truncated: false,
  });
  assert.equal(getCompletedActionPlanJobResult({ done: true, result: completeResult }), null);
});

test('event errors remain observable and cannot mark a job successful', async () => {
  const events = [];
  await readActionPlanJobEvents(response([
    { sequence: 1, done: true },
    { sequence: 2, error: { code: 'failed', message: 'Provider error' } },
  ]), { onEvent: (event) => events.push(event) });
  assert.equal(getActionPlanJobError(events[1].error), 'Provider error');
  assert.equal(getCompletedActionPlanJobResult({ status: 'failed', result: completeResult }), null);
});

test('truncated replay stops appending partial output and asks the caller to read the snapshot', async () => {
  const events = [];
  const outcome = await readActionPlanJobEvents(response([
    { truncated: true, sequence: 40 }, { sequence: 41, log: 'unreliable tail' },
  ]), { onEvent: (event) => events.push(event) });
  assert.equal(outcome.truncated, true);
  assert.equal(outcome.cursor, 0);
  assert.equal(events.length, 1);
});

test('a single oversized event also invalidates progress until the complete snapshot arrives', async () => {
  const events = [];
  const outcome = await readActionPlanJobEvents(response([
    { sequence: 5, event_truncated: true }, { sequence: 6, log: 'unreliable tail' },
  ]), { onEvent: (event) => events.push(event) });
  assert.equal(outcome.truncated, true);
  assert.equal(events.length, 1);
});

test('invalid event framing fails observation rather than becoming user content', async () => {
  await assert.rejects(readActionPlanJobEvents(new Response('{not json}')), SyntaxError);
  await assert.rejects(readActionPlanJobEvents(response([{ log: 'no sequence' }])), /event sequence/);
  await assert.rejects(readActionPlanJobEvents(new Response('failure', { status: 500 })), /500/);
});

test('startup only discovers jobs and schedules a serial two-second observation poll', async () => {
  const f = fixture();
  await f.monitor.start();
  assert.deepEqual(f.requests.map(({ path }) => path), [ACTION_PLAN_JOBS_PATH]);
  assert.equal(f.requests[0].options.method, undefined);
  assert.equal(f.timers[0].delay, 2000);
  await f.timers.shift().callback();
  assert.equal(f.requests.length, 2);
  assert.ok(f.requests.every(({ options }) => !options.method));
  f.monitor.stop();
  assert.equal(f.timers[0].cancelled, true);
});

test('reload reconnects an active manual job and unmount cancels only event observation', async () => {
  const f = fixture({
    fetchJson: async () => ({ active: runningJob, jobs: [runningJob] }),
  });
  await f.monitor.start();
  await flush();
  assert.equal(f.snapshots[0].id, runningJob.id);
  assert.equal(f.cancelledReaders(), 0);
  f.monitor.stop();
  await flush();
  assert.equal(f.cancelledReaders(), 1);
  assert.equal(f.errors.length, 0);
});

test('background jobs do not stream over the displayed plan and only expose successful complete results', async () => {
  let job = { ...runningJob, trigger: 'source_changed' };
  let streamCalls = 0;
  const f = fixture({
    fetchJson: async () => ({ active: isActiveActionPlanJob(job) ? job : null, jobs: [job] }),
    fetchStream: async () => { streamCalls += 1; return response([]); },
  });
  await f.monitor.start();
  assert.equal(getCompletedActionPlanJobResult(f.snapshots.at(-1)), null);
  job = { ...job, status: 'succeeded', result: completeResult };
  await f.timers.shift().callback();
  assert.equal(getCompletedActionPlanJobResult(f.snapshots.at(-1)), completeResult);
  assert.equal(streamCalls, 0);
  f.monitor.stop();
});

test('disconnected event observation resumes from its cursor without submitting generation again', async () => {
  const paths = [];
  const f = fixture({
    fetchJson: async (path) => path === ACTION_PLAN_JOBS_PATH
      ? { active: runningJob, jobs: [runningJob] } : runningJob,
    fetchStream: async (path) => {
      paths.push(path);
      return response([{ sequence: 1, log: 'chunk' }]);
    },
  });
  await f.monitor.start();
  await flush();
  await f.timers.shift().callback();
  await flush();
  assert.deepEqual(paths, [`${ACTION_PLAN_JOBS_PATH}/job-1/events?after=0`, `${ACTION_PLAN_JOBS_PATH}/job-1/events?after=1`]);
  assert.equal(f.events.length, 1);
  assert.ok(f.snapshots.every((job) => job.status === 'running'));
  f.monitor.stop();
});

test('a done event reads authoritative status and does not finish a still-running job', async () => {
  const f = fixture({
    fetchJson: async (path) => path === ACTION_PLAN_JOBS_PATH ? { active: runningJob, jobs: [] } : runningJob,
    fetchStream: async () => response([{ sequence: 1, done: true }]),
  });
  await f.monitor.start();
  await flush();
  assert.equal(f.events[0].done, true);
  assert.equal(f.snapshots.at(-1).status, 'running');
  f.monitor.stop();
});

test('truncated replay retrieves the complete result and never appends the retained tail', async () => {
  const finished = { ...runningJob, status: 'succeeded', event_cursor: 50, result: completeResult };
  const f = fixture({
    fetchJson: async (path) => path === ACTION_PLAN_JOBS_PATH ? { active: runningJob, jobs: [] } : finished,
    fetchStream: async () => response([{ sequence: 40, truncated: true }, { sequence: 41, log: 'tail' }]),
  });
  await f.monitor.start();
  await flush();
  assert.equal(f.events.length, 1);
  assert.equal(getCompletedActionPlanJobResult(f.snapshots.at(-1)), completeResult);
  f.monitor.stop();
});

test('Stop calls the explicit cancel endpoint and keeps observing cancelling status', async () => {
  const calls = [];
  const job = { ...runningJob, trigger: 'startup' };
  const f = fixture({
    fetchJson: async (path, options) => {
      calls.push({ path, options });
      return options.method === 'POST' ? { ...job, status: 'cancelling' } : { active: job, jobs: [] };
    },
  });
  await f.monitor.start();
  await f.monitor.cancelActive();
  assert.equal(calls[1].path, `${ACTION_PLAN_JOBS_PATH}/job-1/cancel`);
  assert.equal(calls[1].options.method, 'POST');
  assert.equal(f.snapshots.at(-1).status, 'cancelling');
  assert.equal(f.timers.length, 1);
  f.monitor.stop();
  assert.equal(calls.length, 2);
});

test('manual requests submit the generation payload once and adopt a reused active job', async () => {
  const calls = [];
  const f = fixture({
    fetchJson: async (path, options) => {
      calls.push({ path, options });
      return { ...runningJob, trigger: 'startup', reused: true };
    },
  });
  const payload = { model: 'chosen-model', reasoning_effort: 'high', replace_today: false };
  const job = await f.monitor.submit(payload);
  assert.equal(job.reused, true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, ACTION_PLAN_JOBS_PATH);
  assert.equal(calls[0].options.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].options.body), payload);
  assert.equal(f.snapshots.length, 1);
  f.monitor.stop();
});

test('an older list response cannot replace a newly submitted job', async () => {
  const pending = deferred();
  const job = { ...runningJob, id: 'new-job', trigger: 'startup' };
  const f = fixture({
    fetchJson: async (path, options) => options.method === 'POST' ? job : pending.promise,
  });
  const started = f.monitor.start();
  assert.equal(f.timers.length, 0);
  await f.monitor.submit({});
  pending.resolve({ jobs: [{ ...runningJob, status: 'succeeded', result: completeResult }], active: null });
  await started;
  assert.deepEqual(f.snapshots.map((snapshot) => snapshot.id), ['new-job']);
  f.monitor.stop();
});

test('late responses after unmount cannot update the UI or submit a cancel request', async () => {
  const pending = deferred();
  let calls = 0;
  const f = fixture({ fetchJson: async () => { calls += 1; return pending.promise; } });
  const started = f.monitor.start();
  f.monitor.stop();
  pending.resolve({ active: runningJob, jobs: [] });
  await started;
  assert.equal(f.snapshots.length, 0);
  assert.equal(f.timers.length, 0);
  assert.equal(calls, 1);
});

test('a backend restart that removes an active job releases UI activity without claiming success or cancellation', async () => {
  let listed = { active: runningJob, jobs: [runningJob] };
  const missing = [];
  const f = fixture({
    fetchJson: async () => listed,
    onMissingJob: (job) => missing.push(job),
  });
  await f.monitor.start();
  await flush();
  listed = { active: null, jobs: [] };
  await f.timers.shift().callback();
  await flush();
  assert.equal(missing[0].id, runningJob.id);
  assert.equal(f.cancelledReaders(), 1);
  assert.equal(f.snapshots.length, 1);
  assert.equal(await f.monitor.cancelActive(), null);
  f.monitor.stop();
});

test('an automatic run cannot hide a successful result that completed between polls', async () => {
  const completed = { ...runningJob, status: 'succeeded', result: completeResult };
  const next = { ...runningJob, id: 'next', trigger: 'source_changed' };
  let listed = { active: next, jobs: [next, completed] };
  const f = fixture({ fetchJson: async () => listed });
  await f.monitor.start();
  assert.deepEqual(f.snapshots.map((job) => [job.id, job.status]), [
    ['job-1', 'succeeded'], ['next', 'running'],
  ]);
  await f.timers.shift().callback();
  assert.equal(f.snapshots.filter((job) => job.status === 'succeeded').length, 1);
  listed = { active: null, jobs: [{ ...next, status: 'failed' }, completed] };
  await f.timers.shift().callback();
  assert.equal(f.snapshots.at(-1).status, 'failed');
  assert.equal(f.snapshots.filter((job) => job.status === 'succeeded').length, 1);
  f.monitor.stop();
});

test('the latest successful result is recovered even when a subsequent automatic run has already failed', async () => {
  const completed = { ...runningJob, status: 'succeeded', result: completeResult };
  const failed = { ...runningJob, id: 'failed', trigger: 'startup', status: 'failed' };
  const f = fixture({ fetchJson: async () => ({ active: null, jobs: [failed, completed] }) });
  await f.monitor.start();
  assert.deepEqual(f.snapshots.map((job) => job.status), ['succeeded', 'failed']);
  f.monitor.stop();
});

test('catching up a previous result never overwrites an active manual stream', async () => {
  const completed = { ...runningJob, id: 'previous', status: 'succeeded', result: completeResult };
  const f = fixture({ fetchJson: async () => ({ active: runningJob, jobs: [runningJob, completed] }) });
  await f.monitor.start();
  assert.deepEqual(f.snapshots.map((job) => job.id), [runningJob.id]);
  f.monitor.stop();
});

test('a previous-day retained job cannot replace the today endpoint response', async () => {
  const yesterday = { ...runningJob, status: 'succeeded', result: { ...completeResult, date: '2026-09-29' } };
  const current = { ...yesterday, id: 'today', result: { ...completeResult, date: '20260930' } };
  let listed = { active: null, jobs: [yesterday] };
  const f = fixture({
    fetchJson: async () => listed,
    shouldDisplayResult: (job) => isActionPlanJobResultCurrent(job, '20260930'),
  });
  await f.monitor.start();
  assert.equal(f.snapshots.length, 0);
  listed = { active: null, jobs: [current, yesterday] };
  await f.timers.shift().callback();
  assert.equal(f.snapshots[0].id, 'today');
  assert.equal(isActionPlanJobResultCurrent(yesterday, '2026-09-30'), false);
  assert.equal(isActionPlanJobResultCurrent({ result: { date: '2026-10-01' } }, '20260930'), true);
  f.monitor.stop();
});

test('restart recovery waits for the saved-view read before scheduling another observation', async () => {
  let listed = { active: { ...runningJob, trigger: 'startup' }, jobs: [] };
  const pending = deferred();
  const f = fixture({ fetchJson: async () => listed, onMissingJob: async () => pending.promise });
  await f.monitor.start();
  listed = { active: null, jobs: [] };
  const reading = f.timers.shift().callback();
  await flush();
  assert.equal(f.timers.length, 0);
  pending.resolve();
  await reading;
  assert.equal(f.timers.length, 1);
  assert.equal(f.snapshots.length, 1);
  f.monitor.stop();
});

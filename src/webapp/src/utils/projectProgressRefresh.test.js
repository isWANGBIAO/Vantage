import test from 'node:test';
import assert from 'node:assert/strict';
import * as progressRefresh from './projectProgressRefresh.js';

const { createProjectProgressRefresh } = progressRefresh;

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

test('existing progress stays visible during refresh and after a refresh error', () => {
  assert.equal(typeof progressRefresh.getProjectProgressViewState, 'function');
  const { getProjectProgressViewState } = progressRefresh;
  const saved = { stats: { total_tasks: 2 } };
  assert.equal(getProjectProgressViewState({ data: null, loading: true, error: null }), 'loading');
  assert.equal(getProjectProgressViewState({ data: null, loading: false, error: 'failed' }), 'error');
  assert.equal(getProjectProgressViewState({ data: saved, loading: true, error: null }), 'content');
  assert.equal(getProjectProgressViewState({ data: saved, loading: false, error: 'failed' }), 'content');
});

test('mount, focus and manual refresh share one in-flight progress request', async () => {
  const focusTarget = new EventTarget();
  const first = deferred();
  const second = deferred();
  const calls = [];
  const data = [];
  const loading = [];
  const refresh = createProjectProgressRefresh({
    focusTarget,
    load: (signal) => { calls.push(signal); return calls.length === 1 ? first.promise : second.promise; },
    onData: (value) => data.push(value),
    onError: (error) => { throw error; },
    onLoading: (value) => loading.push(value),
  });

  refresh.start();
  focusTarget.dispatchEvent(new Event('focus'));
  const manual = refresh.refresh();
  await Promise.resolve();
  assert.equal(calls.length, 1);
  assert.deepEqual(loading, [true]);

  first.resolve({ stats: { total_tasks: 1 } });
  await manual;
  assert.deepEqual(data, [{ stats: { total_tasks: 1 } }]);
  assert.deepEqual(loading, [true, false]);

  focusTarget.dispatchEvent(new Event('focus'));
  await Promise.resolve();
  assert.equal(calls.length, 2);
  second.resolve({ stats: { total_tasks: 2 } });
  await refresh.refresh();
  assert.deepEqual(data.map((value) => value.stats.total_tasks), [1, 2]);
  refresh.dispose();
});

test('unmount aborts the request and blocks stale result and state updates', async () => {
  const focusTarget = new EventTarget();
  const pending = deferred();
  const data = [];
  const errors = [];
  const loading = [];
  let signal;
  let calls = 0;
  const refresh = createProjectProgressRefresh({
    focusTarget,
    load: (requestSignal) => { signal = requestSignal; calls += 1; return pending.promise; },
    onData: (value) => data.push(value),
    onError: (error) => errors.push(error),
    onLoading: (value) => loading.push(value),
  });

  refresh.start();
  const pendingRequest = refresh.refresh();
  await Promise.resolve();
  assert.equal(signal.aborted, false);
  refresh.dispose();
  assert.equal(signal.aborted, true);
  pending.resolve({ stale: true });
  await pendingRequest;
  await refresh.refresh();
  await Promise.resolve();
  focusTarget.dispatchEvent(new Event('focus'));
  await Promise.resolve();
  assert.equal(calls, 1);
  assert.deepEqual(data, []);
  assert.deepEqual(errors, []);
  assert.deepEqual(loading, [true]);
});

test('a failed progress load reports an error and allows a later retry', async () => {
  const focusTarget = new EventTarget();
  const errors = [];
  const data = [];
  const loading = [];
  let calls = 0;
  const refresh = createProjectProgressRefresh({
    focusTarget,
    load: async () => {
      calls += 1;
      if (calls === 1) throw new Error('offline');
      return { ready: true };
    },
    onData: (value) => data.push(value),
    onError: (error) => errors.push(error.message),
    onLoading: (value) => loading.push(value),
  });

  refresh.start();
  await refresh.refresh();
  assert.deepEqual(errors, ['offline']);
  await refresh.refresh();
  assert.deepEqual(data, [{ ready: true }]);
  assert.deepEqual(loading, [true, false, true, false]);
  refresh.dispose();
});

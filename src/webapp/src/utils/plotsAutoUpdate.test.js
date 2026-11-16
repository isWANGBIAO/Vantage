import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { setImmediate } from 'node:timers/promises';
import { createPlotsUpdater, PLOTS_CHECK_INTERVAL_MS, preservePlotZoom } from './plotsAutoUpdate.js';

const revision = (name) => createHash('sha256').update(name).digest('hex');
const full = (name, value = 1) => ({ source_revision: revision(name), charts: [{ id: 'sleep', value }], warnings: [] });
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function harness(fetchJson) {
  const timers = new Map();
  const data = [], errors = [], states = [];
  let id = 0;
  const updater = createPlotsUpdater({ fetchJson,
    onData: (value) => data.push(value), onError: (value) => errors.push(value), onState: (value) => states.push(value),
    setTimer(callback, delay) { timers.set(++id, { callback, delay }); return id; },
    clearTimer(key) { timers.delete(key); },
  });
  return { updater, timers, data, errors, states,
    async tick() {
      const [key, timer] = timers.entries().next().value;
      timers.delete(key);
      assert.equal(timer.delay, PLOTS_CHECK_INTERVAL_MS);
      timer.callback();
      await setImmediate();
    },
  };
}

test('only active plots poll every 30 seconds; unchanged revision does not publish/repaint', async () => {
  const calls = [];
  const h = harness(async (url) => {
    calls.push(url);
    return calls.length === 1 ? full('a') : { unchanged: true, source_revision: revision('a') };
  });
  await h.updater.check();
  assert.equal(calls.length, 0);
  h.updater.setActive(true);
  await setImmediate();
  assert.equal(h.data.length, 1);
  await h.tick();
  assert.deepEqual(calls, ['/api/v1/plots/data', `/api/v1/plots/data?known_revision=${revision('a')}`]);
  assert.equal(h.data.length, 1);
  h.updater.setActive(false);
  assert.equal(h.timers.size, 0);
  await h.updater.check();
  assert.equal(calls.length, 2);
  h.updater.setActive(true);
  await setImmediate();
  assert.equal(calls.length, 3);
  h.updater.dispose();
});

test('focus checks coalesce with active request rather than overlap', async () => {
  const pending = deferred();
  let calls = 0;
  const h = harness(() => { calls++; return pending.promise; });
  h.updater.setActive(true);
  h.updater.check();
  h.updater.check();
  await setImmediate();
  assert.equal(calls, 1);
  pending.resolve(full('a'));
  await setImmediate();
  assert.equal(h.data.length, 1);
  h.updater.dispose();
});

test('hide cancels request; reentry waits for old settlement and rejects late data', async () => {
  const first = deferred();
  const calls = [];
  const h = harness((url, options) => {
    calls.push({ url, options });
    return calls.length === 1 ? first.promise : Promise.resolve(full('new', 2));
  });
  h.updater.setActive(true);
  await setImmediate();
  h.updater.setActive(false);
  assert.equal(calls[0].options.signal.aborted, true);
  h.updater.setActive(true);
  await setImmediate();
  assert.equal(calls.length, 1);
  first.resolve(full('old', 0));
  await setImmediate();
  assert.equal(calls.length, 2);
  assert.deepEqual(h.data.map((item) => item.source_revision), [revision('new')]);
  h.updater.dispose();
});

test('failure retains previous charts and automatically retries from same revision', async () => {
  const calls = [];
  const h = harness(async (url) => {
    calls.push(url);
    if (calls.length === 2) throw new Error('synthetic read lock');
    return full(calls.length === 1 ? 'a' : 'b', calls.length);
  });
  h.updater.setActive(true);
  await setImmediate();
  await h.tick();
  assert.equal(h.data.length, 1);
  assert.equal(h.errors.at(-1).message, 'synthetic read lock');
  await h.tick();
  assert.equal(calls[2], `/api/v1/plots/data?known_revision=${revision('a')}`);
  assert.equal(h.data.at(-1).source_revision, revision('b'));
  assert.equal(h.errors.at(-1), null);
  assert.ok(h.states.slice(1).every((item) => !item.loading));
  h.updater.dispose();
});

test('manual refresh serializes after cancelled poll, clears backend cache and reads without revision', async () => {
  const pending = deferred();
  const calls = [];
  const h = harness((url, options) => {
    calls.push({ url, options });
    if (calls.length === 1) return Promise.resolve(full('a'));
    if (calls.length === 2) return pending.promise;
    return Promise.resolve(url.endsWith('/refresh') ? { status: 'ready' } : full('b', 2));
  });
  h.updater.setActive(true);
  await setImmediate();
  h.updater.check();
  await setImmediate();
  h.updater.refresh();
  assert.equal(calls[1].options.signal.aborted, true);
  assert.equal(calls.length, 2);
  pending.resolve(full('stale', 99));
  await setImmediate();
  assert.deepEqual(calls.map((item) => item.url), ['/api/v1/plots/data', `/api/v1/plots/data?known_revision=${revision('a')}`,
    '/api/v1/plots/refresh', '/api/v1/plots/data']);
  assert.equal(calls[2].options.method, 'POST');
  assert.equal(h.data.at(-1).source_revision, revision('b'));
  assert.equal(h.data.some((item) => item.source_revision === revision('stale')), false);
  h.updater.dispose();
});

test('dispose aborts transport and no late callbacks or timers survive', async () => {
  const pending = deferred();
  let signal;
  const h = harness((url, options) => { signal = options.signal; return pending.promise; });
  h.updater.setActive(true);
  await setImmediate();
  const stateCount = h.states.length;
  h.updater.dispose();
  pending.resolve(full('late'));
  await setImmediate();
  assert.equal(signal.aborted, true);
  assert.equal(h.data.length, 0);
  assert.equal(h.errors.length, 0);
  assert.equal(h.states.length, stateCount);
  assert.equal(h.timers.size, 0);
});

test('malformed or mismatched unchanged responses never advance a revision', async () => {
  let count = 0;
  const h = harness(async () => ++count === 1 ? { unchanged: true, source_revision: 'missing' }
    : count === 2 ? full('a') : { unchanged: true, source_revision: 'other' });
  h.updater.setActive(true);
  await setImmediate();
  assert.equal(h.data.length, 0);
  assert.match(h.errors.at(-1).message, /Invalid unchanged/);
  await h.tick();
  await h.tick();
  assert.equal(h.data.length, 1);
  assert.match(h.errors.at(-1).message, /Invalid unchanged/);
  h.updater.dispose();
});

test('partial failures update healthy charts but retain only failed previous healthy series', async () => {
  const old = { source_revision: revision('a'), charts: [{ id: 'sleep', value: 1 }, { id: 'running', value: 1 }], warnings: [] };
  const partial = { retry_required: true, charts: [{ id: 'sleep', value: 2 }, { id: 'running', error: 'unavailable' }], warnings: [{ id: 'running' }] };
  const calls = [];
  const h = harness(async (url) => {
    calls.push(url);
    if (calls.length === 1) return old;
    if (calls.length < 4) return structuredClone(partial);
    return { ...full('b', 3), charts: [{ id: 'sleep', value: 3 }, { id: 'running', value: 2 }] };
  });
  h.updater.setActive(true);
  await setImmediate();
  await h.tick();
  assert.deepEqual(h.data.at(-1).charts, [{ id: 'sleep', value: 2 }, { id: 'running', value: 1 }]);
  assert.equal(h.errors.at(-1).message, 'plots_retry_required');
  await h.tick();
  assert.equal(h.data.length, 2, 'identical partial retries must not repaint');
  assert.equal(calls[2], '/api/v1/plots/data');
  await h.tick();
  assert.equal(h.data.at(-1).source_revision, revision('b'));
  assert.equal(h.errors.at(-1), null);
  h.updater.dispose();
});

test('partial data cannot be declared current by an unchanged response for the old full revision', async () => {
  const responses = [full('a'), { retry_required: true, charts: [{ id: 'sleep', value: 2 }] },
    { unchanged: true, source_revision: revision('a') }, full('a')];
  const urls = [];
  const h = harness(async (url) => { urls.push(url); return responses.shift(); });
  h.updater.setActive(true);
  await setImmediate();
  await h.tick();
  await h.tick();
  assert.equal(urls[2], '/api/v1/plots/data');
  assert.match(h.errors.at(-1).message, /Invalid unchanged/);
  assert.equal(h.data.at(-1).charts[0].value, 2);
  await h.tick();
  assert.equal(h.data.at(-1).charts[0].value, 1);
  assert.equal(h.errors.at(-1), null);
  h.updater.dispose();
});

test('initial partial results are visible and retry without accepting failed revision', async () => {
  const calls = [];
  const h = harness(async (url) => {
    calls.push(url);
    return calls.length === 1 ? { retry_required: true, charts: [{ id: 'sleep', error: 'busy' }] } : full('good');
  });
  h.updater.setActive(true);
  await setImmediate();
  assert.equal(h.data.length, 1);
  await h.tick();
  assert.equal(calls[1], '/api/v1/plots/data');
  assert.equal(h.data.at(-1).source_revision, revision('good'));
  h.updater.dispose();
});

test('intentional no-data result replaces an old healthy chart and accepts new revision', async () => {
  const calls = [];
  const h = harness(async (url) => {
    calls.push(url);
    if (calls.length === 1) return full('a');
    if (calls.length === 2) return { source_revision: revision('b'), charts: [
      { id: 'sleep', empty: true, error: 'No valid sleep records', retry_required: false },
    ] };
    return { unchanged: true, source_revision: revision('b') };
  });
  h.updater.setActive(true);
  await setImmediate();
  await h.tick();
  assert.equal(h.data.at(-1).charts[0].empty, true);
  assert.equal(h.data.at(-1).source_revision, revision('b'));
  await h.tick();
  assert.equal(calls[2], `/api/v1/plots/data?known_revision=${revision('b')}`);
  assert.equal(h.errors.at(-1), null);
  h.updater.dispose();
});

test('invalid or missing full revisions are never sent back and cannot poison later checks', async (t) => {
  for (const bad of [undefined, '', 'x'.repeat(64), 'A'.repeat(64), 'a'.repeat(63), 'a'.repeat(65)]) {
    await t.test(String(bad), async () => {
      const calls = [];
      const h = harness(async (url) => {
        calls.push(url);
        if (calls.length === 1) return full('a');
        if (calls.length === 2) return { ...full('bad', 2), source_revision: bad };
        if (calls.length === 3) return full('b', 3);
        return { unchanged: true, source_revision: revision('b') };
      });
      h.updater.setActive(true);
      await setImmediate();
      await h.tick();
      await h.tick();
      assert.equal(calls[2], '/api/v1/plots/data', 'invalid revision must force an unconditional read');
      await h.tick();
      assert.equal(calls[3], `/api/v1/plots/data?known_revision=${revision('b')}`);
      assert.equal(h.errors.at(-1), null);
      h.updater.dispose();
    });
  }
});

test('generic chart refresh preserves percentage zoom rather than stale source dates', () => {
  const option = { dataZoom: [{ start: 0, end: 100, startValue: 'old', endValue: 'old', type: 'slider' }] };
  assert.deepEqual(preservePlotZoom(option, [{ start: 25, end: 60 }]).dataZoom,
    [{ start: 25, end: 60, type: 'slider' }]);
  assert.equal(preservePlotZoom(option, null), option);
  assert.deepEqual(preservePlotZoom(option, [{ start: NaN, end: 60 }]), option);
});

test('Plots wires tab/document visibility, focus, cleanup and manual refresh without unmounting charts', () => {
  const source = readFileSync(new URL('../components/Plots.jsx', import.meta.url), 'utf8');
  const app = readFileSync(new URL('../App.jsx', import.meta.url), 'utf8');
  assert.match(app, /<Plots theme=\{theme\} isVisible=\{activeTab === 'plots'\}/);
  assert.match(source, /document\.addEventListener\('visibilitychange', syncVisibility\)/);
  assert.match(source, /window\.addEventListener\('focus', onFocus\)/);
  assert.match(source, /updater\.dispose\(\)/);
  assert.match(source, /updaterRef\.current\?\.refresh\(\)/);
  assert.match(source, /setIsLoading\(loading\)/);
});

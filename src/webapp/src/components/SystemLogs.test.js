import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const systemLogsSource = readFileSync(new URL('./SystemLogs.jsx', import.meta.url), 'utf8');

test('SystemLogs polls only while visible and delegates severity coloring', () => {
  assert.ok(systemLogsSource.includes('export default function SystemLogs({ isVisible = false })'));
  assert.ok(systemLogsSource.includes('if (!isVisible)'));
  assert.ok(systemLogsSource.includes('fetchLogs();'));
  assert.ok(systemLogsSource.includes('resolveSystemLogColor'));
});

function startPollingEffect() {
  const start = systemLogsSource.indexOf('    useEffect(() => {');
  const end = systemLogsSource.indexOf('    }, [isVisible, paused]);', start);
  const effectSource = systemLogsSource.slice(start, end) + '    }, [isVisible, paused]);';
  const timers = new Map();
  const pending = [];
  const updates = [];
  let cleanup;
  let nextId = 0;
  const schedule = (callback) => { timers.set(++nextId, callback); return nextId; };
  new Function('useEffect', 'isVisible', 'paused', 'fetchBackendJson', 'setLogs',
    'setInterval', 'clearInterval', 'setTimeout', 'clearTimeout', effectSource)(
    (effect) => { cleanup = effect(); }, true, false,
    (_path, options) => new Promise((resolve) => pending.push({ resolve, options })),
    (logs) => updates.push(logs), schedule, (id) => timers.delete(id),
    schedule, (id) => timers.delete(id),
  );
  return { cleanup, timers, pending, updates };
}

test('slow log requests cannot overlap and overwrite newer results', async () => {
  const poll = startPollingEffect();
  assert.equal(poll.pending.length, 1);
  assert.equal(poll.timers.size, 0, 'No next request until the active request settles');
  poll.pending[0].resolve({ logs: ['first'] });
  await Promise.resolve();
  assert.deepEqual(poll.updates, [['first']]);
  assert.equal(poll.timers.size, 1);
  poll.cleanup();
  assert.equal(poll.timers.size, 0);
});

test('pausing or hiding logs aborts the request and ignores a late response', async () => {
  const poll = startPollingEffect();
  poll.cleanup();
  poll.pending[0].resolve({ logs: ['arrived after pause'] });
  await Promise.resolve();
  assert.deepEqual(poll.updates, []);
  assert.equal(poll.pending[0].options.signal.aborted, true);
  assert.equal(poll.timers.size, 0);
});

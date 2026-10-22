import test from 'node:test';
import assert from 'node:assert/strict';
import { createCameraPreviewLifecycle } from './cameraPreviewLifecycle.js';

function fixture() {
  const states = [];
  const timers = new Map();
  let id = 0;
  const lifecycle = createCameraPreviewLifecycle({
    onChange: (state) => states.push(state),
    schedule: (callback, delay) => { timers.set(++id, { callback, delay }); return id; },
    cancel: (timer) => timers.delete(timer),
  });
  return { lifecycle, states, timers, advance() { const [key, timer] = timers.entries().next().value; timers.delete(key); timer.callback(); } };
}

test('preview becomes live only on the current image load, and retries a broken stream', () => {
  const f = fixture();
  assert.equal(f.states.at(-1).phase, 'connecting');
  f.lifecycle.loaded(0);
  assert.equal(f.states.at(-1).phase, 'live');
  f.lifecycle.failed(0);
  assert.equal(f.states.at(-1).phase, 'waiting');
  f.lifecycle.loaded(0);
  assert.equal(f.states.at(-1).phase, 'waiting');
  assert.equal(f.timers.values().next().value.delay, 1000);
  f.advance();
  assert.equal(f.states.at(-1).attempt, 1);
  f.lifecycle.loaded(0);
  assert.equal(f.states.at(-1).phase, 'connecting');
  f.lifecycle.loaded(1);
  assert.equal(f.states.at(-1).phase, 'live');
});

test('five bounded retries stop instead of opening an endless stream loop', () => {
  const f = fixture();
  const delays = [];
  for (let attempt = 0; attempt < 5; attempt += 1) {
    f.lifecycle.failed(attempt);
    delays.push(f.timers.values().next().value.delay);
    f.advance();
  }
  f.lifecycle.failed(5);
  assert.deepEqual(delays, [1000, 2000, 4000, 8000, 15000]);
  assert.equal(f.states.at(-1).phase, 'failed');
  assert.equal(f.timers.size, 0);
});

test('hide/unmount cancels scheduled retries and ignores late image callbacks', () => {
  const f = fixture();
  f.lifecycle.failed(0);
  const count = f.states.length;
  f.lifecycle.close();
  f.lifecycle.loaded(0);
  f.lifecycle.failed(0);
  assert.equal(f.states.length, count);
  assert.equal(f.timers.size, 0);
});

const test = require('node:test');
const assert = require('node:assert/strict');

test('quit waits for the Never Stop runner and keeps running intent for next launch', async () => {
  const { createNeverStopQuitGate } = require('./neverStopLifecycle.cjs');
  let release;
  const waiting = new Promise(resolve => { release = resolve; });
  const calls = [];
  const gate = createNeverStopQuitGate({
    getServiceReady: () => Promise.resolve({ shutdown: async options => { calls.push(options); await waiting; } }),
    completeQuit: () => calls.push('quit'),
    reportError: error => { throw error; },
  });
  const event = { preventDefault: () => calls.push('prevent') };
  assert.equal(gate(event), false);
  assert.equal(gate(event), false);
  await Promise.resolve();
  assert.deepEqual(calls.slice(0, 2), ['prevent', 'prevent']);
  release();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls.filter(value => typeof value === 'object'), [{ preserveIntent: true }]);
  assert.equal(calls.at(-1), 'quit');
  assert.equal(gate(event), true);
});

test('failed shutdown cancels quit and allows a later retry', async () => {
  const { createNeverStopQuitGate } = require('./neverStopLifecycle.cjs');
  let attempts = 0;
  const errors = [];
  const gate = createNeverStopQuitGate({
    getServiceReady: () => Promise.resolve({
      shutdown: async () => {
        attempts++;
        if (attempts === 1) throw new Error('cannot stop owned process');
      },
    }),
    completeQuit: () => {},
    reportError: error => errors.push(error.message),
  });
  const event = { preventDefault: () => {} };
  assert.equal(gate(event), false);
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(errors, ['cannot stop owned process']);
  assert.equal(gate(event), false);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(attempts, 2);
  assert.equal(gate(event), true);
});

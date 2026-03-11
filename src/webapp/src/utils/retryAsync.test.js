import test from 'node:test';
import assert from 'node:assert/strict';

import { retryAsync } from './retryAsync.js';

test('retryAsync retries transient failures until the operation succeeds', async () => {
  let attempts = 0;
  const waits = [];

  const result = await retryAsync(async () => {
    attempts += 1;
    if (attempts < 3) {
      throw new Error(`temporary failure ${attempts}`);
    }
    return 'ready';
  }, {
    delaysMs: [25, 50],
    wait: async (delayMs) => {
      waits.push(delayMs);
    },
  });

  assert.equal(result, 'ready');
  assert.equal(attempts, 3);
  assert.deepEqual(waits, [25, 50]);
});

test('retryAsync throws the final error after retries are exhausted', async () => {
  let attempts = 0;

  await assert.rejects(
    retryAsync(async () => {
      attempts += 1;
      throw new Error(`still failing ${attempts}`);
    }, {
      delaysMs: [10, 20],
      wait: async () => {},
    }),
    /still failing 3/,
  );

  assert.equal(attempts, 3);
});

test('retryAsync does not retry errors rejected by shouldRetry', async () => {
  const abortError = new Error('aborted');
  abortError.name = 'AbortError';
  let waits = 0;

  await assert.rejects(
    retryAsync(async () => {
      throw abortError;
    }, {
      delaysMs: [10, 20],
      shouldRetry: (error) => error.name !== 'AbortError',
      wait: async () => {
        waits += 1;
      },
    }),
    (error) => error === abortError,
  );

  assert.equal(waits, 0);
});

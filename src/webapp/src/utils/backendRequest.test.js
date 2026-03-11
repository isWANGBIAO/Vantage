import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildBackendUrl,
  fetchBackend,
  fetchBackendJson,
} from './backendRequest.js';

function jsonResponse(body, init = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

test('buildBackendUrl prefixes relative backend paths', () => {
  assert.equal(buildBackendUrl('/api/status'), 'http://localhost:8000/api/status');
  assert.equal(buildBackendUrl('/static/demo.png'), 'http://localhost:8000/static/demo.png');
  assert.equal(buildBackendUrl('http://example.com/demo'), 'http://example.com/demo');
});

test('fetchBackendJson retries transient GET failures', async () => {
  const originalFetch = globalThis.fetch;
  let attempts = 0;

  globalThis.fetch = async () => {
    attempts += 1;
    if (attempts < 3) {
      throw new Error(`temporary network ${attempts}`);
    }
    return jsonResponse({ ok: true });
  };

  try {
    const data = await fetchBackendJson('/api/status', {
      retryPolicy: 'load',
      wait: async () => {},
    });

    assert.deepEqual(data, { ok: true });
    assert.equal(attempts, 3);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('fetchBackend retries retriable GET http errors', async () => {
  const originalFetch = globalThis.fetch;
  let attempts = 0;

  globalThis.fetch = async () => {
    attempts += 1;
    if (attempts < 2) {
      return jsonResponse({ error: 'busy' }, { status: 503 });
    }
    return jsonResponse({ ok: true });
  };

  try {
    const response = await fetchBackend('/api/system_logs', {
      retryPolicy: 'poll',
      wait: async () => {},
    });

    assert.equal(response.status, 200);
    assert.equal(attempts, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('fetchBackend does not retry non-idempotent mutations by default', async () => {
  const originalFetch = globalThis.fetch;
  let attempts = 0;

  globalThis.fetch = async () => {
    attempts += 1;
    throw new Error('connection refused');
  };

  try {
    await assert.rejects(
      fetchBackend('/api/toggle_detection', {
        method: 'POST',
        retryPolicy: 'mutation',
        wait: async () => {},
      }),
      /connection refused/,
    );

    assert.equal(attempts, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

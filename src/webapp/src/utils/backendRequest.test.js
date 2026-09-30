import test from 'node:test';
import assert from 'node:assert/strict';

import {
  BACKEND_BASE_URL,
  buildBackendUrl,
  fetchBackend,
  fetchBackendJson,
  resolveBackendBaseUrl,
} from './backendRequest.js';

function jsonResponse(body, init = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

test('buildBackendUrl prefixes relative backend paths', () => {
  assert.equal(BACKEND_BASE_URL, 'http://127.0.0.1:8000');
  assert.equal(buildBackendUrl('/api/v1/system/status'), 'http://127.0.0.1:8000/api/v1/system/status');
  assert.equal(buildBackendUrl('/static/demo.png'), 'http://127.0.0.1:8000/static/demo.png');
  assert.equal(buildBackendUrl('http://127.0.0.1:8000/demo'), 'http://127.0.0.1:8000/demo');
  assert.throws(() => buildBackendUrl('http://example.com/demo'), /loopback/);
  assert.throws(() => buildBackendUrl('http://127.0.0.1:8001/demo'), /configured/);
});

test('resolveBackendBaseUrl prefers same-origin http pages', () => {
  assert.equal(
    resolveBackendBaseUrl({ protocol: 'http:', hostname: 'localhost' }),
    '',
  );
  assert.equal(
    resolveBackendBaseUrl({ protocol: 'https:', hostname: '127.0.0.1' }),
    '',
  );
});

test('resolveBackendBaseUrl falls back to loopback backend outside the browser', () => {
  assert.equal(
    resolveBackendBaseUrl({ protocol: 'file:', hostname: 'localhost' }),
    'http://127.0.0.1:8000',
  );
  assert.equal(
    resolveBackendBaseUrl({ protocol: 'file:', hostname: '::1' }),
    'http://127.0.0.1:8000',
  );
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
    const data = await fetchBackendJson('/api/v1/system/status', {
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
    const response = await fetchBackend('/api/v1/system/logs', {
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
      fetchBackend('/api/v1/camera/detection/toggle', {
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


test('backend URL resolution rejects remote browser origins and unsafe paths', () => {
  assert.throws(() => resolveBackendBaseUrl({ protocol: 'https:', hostname: '192.168.31.8' }), /loopback/);
  for (const path of ['//example.com/api', '../api', '/api/../settings', '/api/%2e%2e/settings', 'file:///etc/passwd', 'data:text/plain,secret']) {
    assert.throws(() => buildBackendUrl(path));
  }
});

test('native connection overrides build-time environment and browser uses an explicit loopback URL', () => {
  const platform = { backend: { connection: { baseUrl: 'http://127.0.0.1:8123' } } };
  assert.equal(resolveBackendBaseUrl(undefined, { platform, env: { VANTAGE_BACKEND_URL: 'http://127.0.0.1:8111' } }), 'http://127.0.0.1:8123');
  assert.equal(resolveBackendBaseUrl(undefined, { env: { VANTAGE_BACKEND_PORT: '8111' } }), 'http://127.0.0.1:8111');
  assert.equal(resolveBackendBaseUrl(undefined, { env: { VANTAGE_BACKEND_URL: 'http://localhost:8222' } }), 'http://localhost:8222');
});

test('backend fetches disable redirects even when a caller requests following them', async () => {
  const originalFetch = globalThis.fetch;
  let options;
  globalThis.fetch = async (_url, received) => { options = received; return jsonResponse({ ok: true }); };
  try {
    await fetchBackend('/api/v1/settings', { method: 'PUT', body: '{}', redirect: 'follow' });
    assert.equal(options.redirect, 'error');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('AbortSignal cancels a request during native startup without waiting for readiness', async () => {
  const originalBridge = globalThis.vantagePlatform;
  const originalFetch = globalThis.fetch;
  let release;
  const startup = new Promise(resolve => { release = resolve; });
  const controller = new AbortController();
  let fetched = false;
  globalThis.vantagePlatform = { waitUntilBackendReady: () => startup };
  globalThis.fetch = async () => { fetched = true; return jsonResponse({ ok: true }); };
  try {
    const request = fetchBackend('/api/v1/system/status', { signal: controller.signal });
    controller.abort();
    await assert.rejects(request, { name: 'AbortError' });
    assert.equal(fetched, false);
    release();
    await Promise.resolve();
    assert.equal(fetched, false, 'An aborted startup wait must never issue a late request');
  } finally {
    release();
    globalThis.vantagePlatform = originalBridge;
    globalThis.fetch = originalFetch;
  }
});

test('backend readiness failure propagates without fetching or retrying', async () => {
  const originalBridge = globalThis.vantagePlatform;
  const originalFetch = globalThis.fetch;
  let fetched = false;
  globalThis.vantagePlatform = { waitUntilBackendReady: async () => { throw new Error('startup failed'); } };
  globalThis.fetch = async () => { fetched = true; return jsonResponse({ ok: true }); };
  try {
    await assert.rejects(fetchBackend('/api/v1/system/status'), /startup failed/);
    assert.equal(fetched, false);
  } finally {
    globalThis.vantagePlatform = originalBridge;
    globalThis.fetch = originalFetch;
  }
});

test('packaged renderer stays same-origin and rewrites its configured backend asset URLs', () => {
  const oldBridge = globalThis.vantagePlatform;
  const oldLocation = globalThis.location;
  globalThis.vantagePlatform = { descriptor: { backend: { baseUrl: 'http://127.0.0.1:8765/prefix', rendererOrigin: 'vantage://app' } } };
  globalThis.location = { protocol: 'vantage:', host: 'app', origin: 'vantage://app' };
  try {
    assert.equal(resolveBackendBaseUrl(), '');
    assert.equal(buildBackendUrl('/api/v1/action-plan/jobs'), '/api/v1/action-plan/jobs');
    assert.equal(buildBackendUrl('vantage://app/static/image.png'), '/static/image.png');
    assert.equal(buildBackendUrl('http://127.0.0.1:8765/prefix/static/image.png'), '/static/image.png');
    assert.throws(() => buildBackendUrl('vantage://other/api/v1/system/status'), /trusted renderer/);
    assert.throws(() => buildBackendUrl('http://127.0.0.1:8765/unrelated'), /trusted renderer/);
    assert.throws(() => buildBackendUrl('https://untrusted.invalid/api/v1/system/status'), /trusted renderer/);
  } finally {
    globalThis.vantagePlatform = oldBridge;
    globalThis.location = oldLocation;
  }
});

test('removed renderer environment aliases cannot override the canonical connection', () => {
  assert.equal(resolveBackendBaseUrl(undefined, { env: { VITE_BACKEND_BASE_URL: 'http://localhost:9999' } }), 'http://127.0.0.1:8000');
  assert.equal(resolveBackendBaseUrl(undefined, { env: { VANTAGE_BACKEND_URL: 'http://localhost:8765', VITE_BACKEND_BASE_URL: 'http://localhost:9999' } }), 'http://localhost:8765');
});

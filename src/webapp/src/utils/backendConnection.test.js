import test from 'node:test';
import assert from 'node:assert/strict';
import contract from './backendConnection.cjs';
const { normalizeBackendBaseUrl, resolveBackendConnection, buildConnectionUrl } = contract;

test('all local connection users honor URL, host/port, and defaults in priority order', () => {
  assert.equal(resolveBackendConnection().baseUrl, 'http://127.0.0.1:8000');
  assert.equal(resolveBackendConnection({ env: { VANTAGE_BACKEND_PORT: '8765' } }).baseUrl, 'http://127.0.0.1:8765');
  assert.equal(resolveBackendConnection({ env: { VANTAGE_BACKEND_HOST: '::1', VANTAGE_BACKEND_PORT: '8765' } }).baseUrl, 'http://[::1]:8765');
  const env = { VANTAGE_BACKEND_URL: 'http://localhost:8765', VANTAGE_BACKEND_HOST: 'not-local.invalid', VANTAGE_BACKEND_PORT: 'bad' };
  assert.equal(resolveBackendConnection({ env }).baseUrl, 'http://localhost:8765');
  assert.equal(resolveBackendConnection({ baseUrl: 'http://127.0.0.2:8123', env }).baseUrl, 'http://127.0.0.2:8123');
});

test('connection accepts loopback URLs and safe optional prefixes only', () => {
  for (const url of ['http://127.0.0.1:8123', 'https://localhost:9443/vantage', 'http://[::1]:8123', 'http://127.255.255.254:8123']) {
    assert.equal(normalizeBackendBaseUrl(`${url}/`), url);
  }
  const connection = resolveBackendConnection({ baseUrl: 'http://localhost:8123/vantage' });
  assert.equal(buildConnectionUrl(connection, '/api/v1/system/status'), 'http://localhost:8123/vantage/api/v1/system/status');
});

test('connection rejects non-loopback, deceptive authority, credentials, redirects, and invalid ports', () => {
  for (const url of [
    'http://example.com', 'http://192.168.1.2', 'http://0.0.0.0', 'file:///etc/passwd',
    'http://localhost.example.com', 'http://localhost@evil.invalid', 'http://user:secret@localhost',
    'http://127.0.0.1?token=secret', 'http://127.0.0.1#fragment', 'http://127.0.0.1:0',
    'http://127.0.0.1:65536', 'http://127.1', 'http://2130706433', 'http://0x7f000001',
    'http://127.0.0.1\\@evil.invalid',
  ]) assert.throws(() => normalizeBackendBaseUrl(url), undefined, url);
  for (const port of ['0', '-1', '1.5', '65536', 'oops']) {
    assert.throws(() => resolveBackendConnection({ env: { VANTAGE_BACKEND_PORT: port } }));
  }
});

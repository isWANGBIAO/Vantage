import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { mkdtemp, mkdir, writeFile, symlink, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import appProtocol from './appProtocol.cjs';

const { APP_ORIGIN, APP_SCHEME_PRIVILEGES, createAppProtocolHandler, isTrustedAppNetworkRequest } = appProtocol;
const trustedRequest = (url, init) => {
  const request = new Request(`${APP_ORIGIN}${url}`, init);
  Object.defineProperty(request, 'initiatorOrigin', { value: APP_ORIGIN });
  return request;
};

async function withAssets(run) {
  const root = await mkdtemp(path.join(tmpdir(), 'vantage-protocol-test-'));
  const bundle = path.join(root, 'dist');
  await mkdir(path.join(bundle, 'assets'), { recursive: true });
  await writeFile(path.join(bundle, 'index.html'), '<html>Trusted app</html>');
  await writeFile(path.join(bundle, 'assets', 'app.js'), 'window.loaded = true;');
  await writeFile(path.join(root, 'private.js'), 'outside-secret');
  try { await run({ root, bundle }); } finally { await rm(root, { recursive: true, force: true }); }
}

async function withBackend(listener, run) {
  const server = createServer(listener);
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  try { await run({ baseUrl: `http://127.0.0.1:${server.address().port}` }); }
  finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}

test('packaged scheme is standard, secure and streaming without bypassing CSP', () => {
  assert.equal(APP_SCHEME_PRIVILEGES.standard, true);
  assert.equal(APP_SCHEME_PRIVILEGES.secure, true);
  assert.equal(APP_SCHEME_PRIVILEGES.supportFetchAPI, true);
  assert.equal(APP_SCHEME_PRIVILEGES.corsEnabled, true);
  assert.equal(APP_SCHEME_PRIVILEGES.stream, true);
  assert.notEqual(APP_SCHEME_PRIVILEGES.bypassCSP, true);
});

test('packaged assets enforce host, containment, symlinks, MIME, and CSP', async () => withAssets(async ({ root, bundle }) => {
  const handle = createAppProtocolHandler({ assetRoot: bundle, connection: { baseUrl: 'http://127.0.0.1:8000' } });
  const document = await handle(new Request(`${APP_ORIGIN}/index.html`));
  assert.equal(document.status, 200);
  assert.equal(await document.text(), '<html>Trusted app</html>');
  assert.match(document.headers.get('content-security-policy'), /connect-src 'self'/);
  assert.equal((await handle(trustedRequest('/assets/app.js'))).headers.get('content-type'), 'text/javascript; charset=utf-8');
  for (const url of ['vantage://evil/index.html', 'vantage://app:99/index.html', 'vantage://user@app/index.html', 'vantage://app/%252e%252e/private.js', 'vantage://app/%2f..%2fprivate.js', 'vantage://app/..%5cprivate.js']) {
    assert.equal((await handle({ url })).status, 400, url);
  }
  assert.equal((await handle(trustedRequest('/package.json'))).status, 404);
  assert.equal((await handle(trustedRequest('/private.js'))).status, 404);
  await symlink(path.join(root, 'private.js'), path.join(bundle, 'assets', 'escape.js'));
  assert.equal((await handle(trustedRequest('/assets/escape.js'))).status, 403);
  const foreign = new Request(`${APP_ORIGIN}/assets/app.js`);
  Object.defineProperty(foreign, 'initiatorOrigin', { value: 'https://untrusted.invalid' });
  assert.equal((await handle(foreign)).status, 403);
}));

test('session gate rejects external windows, subframes, arbitrary navigation, and missing identities', () => {
  const contents = { id: 7, getURL: () => `${APP_ORIGIN}/index.html` };
  const details = { webContentsId: 7, resourceType: 'xhr', url: `${APP_ORIGIN}/api/status`, frame: { url: `${APP_ORIGIN}/index.html`, parent: null } };
  assert.equal(isTrustedAppNetworkRequest(details, contents), true);
  assert.equal(isTrustedAppNetworkRequest({ ...details, webContentsId: 8 }, contents), false);
  assert.equal(isTrustedAppNetworkRequest({ ...details, webContentsId: undefined }, contents), false);
  assert.equal(isTrustedAppNetworkRequest({ ...details, resourceType: 'subFrame' }, contents), false);
  assert.equal(isTrustedAppNetworkRequest({ ...details, frame: { ...details.frame, parent: {} } }, contents), false);
  assert.equal(isTrustedAppNetworkRequest({ ...details, frame: { url: 'data:text/html,untrusted' } }, contents), false);
  assert.equal(isTrustedAppNetworkRequest({ ...details, url: 'vantage://attacker/api/status' }, contents), false);
  assert.equal(isTrustedAppNetworkRequest({ ...details, resourceType: 'mainFrame' }, contents), false);
  assert.equal(isTrustedAppNetworkRequest({ ...details, resourceType: 'mainFrame', url: `${APP_ORIGIN}/index.html` }, contents), true);
});

test('same-origin JSON POST uses only the configured loopback target and drops ambient credentials', async () => withAssets(async ({ bundle }) => {
  const calls = [];
  await withBackend(async (request, response) => {
    let body = ''; for await (const chunk of request) body += chunk;
    calls.push({ method: request.method, path: request.url, headers: request.headers, body });
    response.setHeader('content-type', 'application/json');
    response.setHeader('set-cookie', 'unwanted=1');
    response.end('{"id":"accepted"}');
  }, async connection => {
    const handle = createAppProtocolHandler({ assetRoot: bundle, connection });
    const response = await handle(trustedRequest('/api/v1/action-plan/jobs', {
      method: 'POST', headers: { 'content-type': 'application/json', 'authorization': 'do-not-forward', cookie: 'private=1', origin: APP_ORIGIN }, body: '{"replace_today":true}',
    }));
    assert.deepEqual(await response.json(), { id: 'accepted' });
    assert.equal(response.headers.has('set-cookie'), false);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].method, 'POST');
    assert.equal(calls[0].path, '/api/v1/action-plan/jobs');
    assert.equal(calls[0].body, '{"replace_today":true}');
    for (const header of ['authorization', 'cookie', 'origin']) assert.equal(calls[0].headers[header], undefined);
    assert.equal((await handle(new Request(`${APP_ORIGIN}/api/status`))).status, 403, 'Ungated direct factory use fails closed');
    assert.equal((await handle(trustedRequest('/static/image.png', { method: 'POST', body: 'x' }))).status, 405);
  });
}));

test('proxy never follows a redirect or exposes its destination to the renderer', async () => withAssets(async ({ bundle }) => {
  let leaked = 0;
  await withBackend((_request, response) => { leaked++; response.end('{}'); }, async destination => {
    await withBackend((_request, response) => { response.writeHead(307, { location: destination.baseUrl }); response.end(); }, async connection => {
      const handle = createAppProtocolHandler({ assetRoot: bundle, connection });
      const result = await handle(trustedRequest('/api/settings', { method: 'POST', body: 'synthetic-private-data' }));
      assert.equal(result.status, 502);
      assert.equal(result.headers.has('location'), false);
      assert.equal(leaked, 0);
    });
  });
}));

test('NDJSON remains streaming and cancelling an observer never posts job cancellation', async () => withAssets(async ({ bundle }) => {
  let closed;
  const didClose = new Promise(resolve => { closed = resolve; });
  let job = 'running'; const calls = [];
  await withBackend((request, response) => {
    calls.push(`${request.method} ${request.url}`);
    if (request.url.endsWith('/events')) {
      response.setHeader('content-type', 'application/x-ndjson');
      response.write('{"step":"first"}\n');
      response.on('close', closed);
    } else { response.setHeader('content-type', 'application/json'); response.end(JSON.stringify({ status: job })); }
  }, async connection => {
    const handle = createAppProtocolHandler({ assetRoot: bundle, connection });
    const response = await handle(trustedRequest('/api/v1/action-plan/jobs/test/events'));
    const reader = response.body.getReader();
    const first = await reader.read();
    assert.equal(new TextDecoder().decode(first.value), '{"step":"first"}\n');
    await reader.cancel();
    await didClose;
    job = 'succeeded';
    const snapshot = await handle(trustedRequest('/api/v1/action-plan/jobs/test'));
    assert.equal((await snapshot.json()).status, 'succeeded');
    assert.deepEqual(calls, ['GET /api/v1/action-plan/jobs/test/events', 'GET /api/v1/action-plan/jobs/test']);
  });
}));

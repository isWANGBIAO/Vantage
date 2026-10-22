import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { EventEmitter } from 'node:events';
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import process from 'node:process';
import { setImmediate } from 'node:timers';

const require = createRequire(import.meta.url);
const { requestBackendStatus, ensureBundledBackendReady, terminateBundledBackendProcess } = require('./backendRuntime.cjs');
async function deadline(promise) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => { timer = setTimeout(() => reject(Error('test deadline exceeded')), 2500); }),
    ]);
  } finally { clearTimeout(timer); }
}

test('a real truncated HTTP 200 status response rejects instead of hanging', async t => {
  const server = http.createServer((_request, response) => {
    response.writeHead(200, { 'Content-Type': 'application/json', 'Content-Length': '100' });
    response.write('{"ready":');
    setImmediate(() => response.destroy());
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  await assert.rejects(deadline(requestBackendStatus({
    url: `http://127.0.0.1:${server.address().port}/status`, timeoutMs: 100,
  })), error => {
    assert.notEqual(error.message, 'test deadline exceeded');
    return true;
  });
});

for (const event of ['error', 'exit']) {
  test(`child ${event} promptly rejects startup while readiness is pending`, async () => {
    const child = Object.assign(new EventEmitter(), { exitCode: null, unref() {} });
    child.on('error', () => {});
    let checks = 0;
    const pending = ensureBundledBackendReady({
      isDev: false, platform: 'linux', env: {}, runtimePaths: {},
      executablePath: '/synthetic/backend', fileExists: () => true,
      loadProviderConfigFn: () => ({ providers: {} }), spawnProcess: () => child,
      onSpawned: () => setImmediate(() => {
        if (event === 'error') child.emit('error', Object.assign(Error('spawn denied'), { code: 'EACCES' }));
        else { child.exitCode = 7; child.emit('exit', 7, null); }
      }),
      waitForStatusFn: async () => {
        if (++checks === 1) throw Error('offline');
        return new Promise(() => {});
      },
    });
    await assert.rejects(deadline(pending), error => {
      assert.match(error.message, /Failed to start bundled backend/);
      assert.notEqual(error.message, 'test deadline exceeded');
      return true;
    });
  });
}

for (const failure of ['spawn-error', 'early-exit']) {
  test(`real child ${failure} cannot leave backend readiness pending`, async () => {
    let checks = 0;
    await assert.rejects(deadline(ensureBundledBackendReady({
      isDev: false, platform: process.platform, env: {}, runtimePaths: {},
      executablePath: process.execPath, fileExists: () => true,
      loadProviderConfigFn: () => ({ providers: {} }),
      spawnProcess: (_file, _args, options) => failure === 'spawn-error'
        ? spawn(`${process.execPath}.vantage-nonexistent`, [], options)
        : spawn(process.execPath, ['-e', 'process.exit(7)'], options),
      waitForStatusFn: async () => {
        if (++checks === 1) throw Error('offline');
        return new Promise(() => {});
      },
    })), /Failed to start bundled backend/);
  });
}

test('a child already exited by signal is never terminated again by stale PID', () => {
  let killed = false;
  terminateBundledBackendProcess({ pid: 123, exitCode: null, signalCode: 'SIGTERM' }, {
    killTree: () => { killed = true; },
  });
  assert.equal(killed, false);
});

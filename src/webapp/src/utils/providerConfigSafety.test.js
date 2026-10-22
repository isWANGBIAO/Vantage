import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { loadProviderConfig } = require('./onboardingConfig.cjs');
const { ensureBundledBackendReady } = require('./backendRuntime.cjs');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(tmpdir(), 'vantage-provider-safety-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const runtimePaths = Object.fromEntries(
    ['data', 'config', 'history', 'log', 'plot', 'cache', 'runtime', 'migration']
      .map(key => [`${key}Dir`, path.join(root, key)]),
  );
  fs.mkdirSync(runtimePaths.configDir, { recursive: true });
  return { runtimePaths, file: path.join(runtimePaths.configDir, 'providers.json') };
}

for (const [name, content] of [
  ['truncated JSON', '{"api_key":"SYNTHETIC-RECOVERABLE-KEY",'],
  ['zero-byte file', ''],
  ['null', 'null'],
  ['array', '[]'],
  ['number', '123'],
  ['string', '"SYNTHETIC-RECOVERABLE-KEY"'],
  ['boolean', 'false'],
  ['invalid UTF-8', Buffer.from([0x7b, 0x22, 0x78, 0x22, 0x3a, 0x22, 0xff, 0x22, 0x7d])],
]) {
  test(`provider loader preserves ${name} and reports a safe recovery error`, t => {
    const { runtimePaths, file } = fixture(t);
    fs.writeFileSync(file, content);
    const original = fs.readFileSync(file);
    assert.throws(() => loadProviderConfig(runtimePaths), error => {
      assert.equal(error.name, 'ConfigurationReadError');
      assert.match(error.message, /providers\.json/);
      assert.match(error.message, /preserved/i);
      assert.match(error.message, /restore|repair/i);
      assert.equal(error.message.includes('SYNTHETIC-RECOVERABLE-KEY'), false);
      assert.equal(error.cause, undefined);
      return true;
    });
    assert.deepEqual(fs.readFileSync(file), original);
  });
}

test('provider loader does not treat access denial as a missing file', t => {
  const { runtimePaths, file } = fixture(t);
  fs.writeFileSync(file, '{"providers":{}}');
  const original = fs.readFileSync(file);
  const readFileSync = fs.readFileSync;
  fs.readFileSync = (candidate, ...args) => {
    if (candidate === file) {
      throw Object.assign(new Error('SYNTHETIC-SECRET-IN-OS-ERROR'), { code: 'EACCES' });
    }
    return readFileSync(candidate, ...args);
  };
  try {
    assert.throws(() => loadProviderConfig(runtimePaths), error => {
      assert.equal(error.name, 'ConfigurationReadError');
      assert.match(error.message, /permissions/i);
      assert.equal(error.message.includes('SYNTHETIC-SECRET'), false);
      return true;
    });
  } finally {
    fs.readFileSync = readFileSync;
  }
  assert.deepEqual(fs.readFileSync(file), original);
});

test('provider loader initializes only a genuinely missing file and keeps valid output stable', t => {
  const { runtimePaths, file } = fixture(t);
  const first = loadProviderConfig(runtimePaths);
  assert.deepEqual(first.providers, {});
  const original = fs.readFileSync(file);
  assert.deepEqual(loadProviderConfig(runtimePaths), first);
  assert.deepEqual(fs.readFileSync(file), original);
});

for (const platform of ['win32', 'darwin']) {
  test(`packaged ${platform} startup preserves malformed provider configuration before spawn`, async t => {
    const { runtimePaths, file } = fixture(t);
    fs.writeFileSync(file, '{"providers":{"synthetic":{"api_key":"SYNTHETIC-ONLY-KEY"}},');
    const original = fs.readFileSync(file);
    await assert.rejects(ensureBundledBackendReady({
      isDev: false, runtimePaths, env: {}, platform,
      executablePath: path.join(runtimePaths.runtimeDir, 'synthetic-backend'),
      fileExists: () => true,
      waitForStatusFn: async () => { throw new Error('synthetic backend offline'); },
      spawnProcess: () => { assert.fail('configuration must be checked before spawning'); },
    }), error => {
      assert.equal(error.name, 'ConfigurationReadError');
      return true;
    });
    assert.deepEqual(fs.readFileSync(file), original);
  });
}

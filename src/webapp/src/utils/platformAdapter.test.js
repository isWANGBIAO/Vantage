import test from 'node:test';
import assert from 'node:assert/strict';
import { createPlatformAdapter, getPlatformAdapter } from './platformAdapter.js';

test('diagnostics is unavailable in a browser and cannot open arbitrary paths', async () => {
  const browser = createPlatformAdapter();
  assert.equal(browser.capabilities.diagnostics, false);
  assert.equal(await browser.diagnostics.getStatus(), null);
  assert.deepEqual(await browser.diagnostics.openDirectory(), { opened: false });
  const calls = [];
  const native = createPlatformAdapter({
    getDiagnosticsStatus: async (...args) => { calls.push(args); return { localOnly: true }; },
    openDiagnosticsDirectory: async (...args) => { calls.push(args); return { opened: true }; },
  });
  assert.equal(native.capabilities.diagnostics, true);
  assert.deepEqual(await native.diagnostics.getStatus(), { localOnly: true });
  assert.deepEqual(await native.diagnostics.openDirectory('/untrusted'), { opened: true });
  assert.deepEqual(calls, [[], []]);
});

test('browser exposes explicit unavailable native capabilities without performing side effects', async () => {
  const platform = createPlatformAdapter();
  assert.equal(platform.kind, 'browser');
  assert.equal(platform.capabilities.customTitleBar, false);
  assert.equal(platform.capabilities.launchAtLogin, false);
  assert.equal(platform.capabilities.openSettingsPath, false);
  assert.equal(platform.capabilities.pickBodyAnalysisDirectory, false);
  assert.deepEqual(await platform.paths.pickBodyAnalysisDirectory('leg'), { path: null });
  assert.deepEqual(await platform.camera.requestAccess(), { granted: false, supported: false });
  assert.deepEqual(await platform.window.setTitleBarTheme('light'), { applied: false });
  assert.deepEqual(await platform.preferences.applySaved(), { applied: false });
  assert.ok(await platform.locale.getSystemLocale());
});

test('body-analysis picker uses one narrow native capability', async () => {
  const calls = [];
  const platform = createPlatformAdapter({
    pickBodyAnalysisDirectory: async (kind) => { calls.push(kind); return { path: 'selected-directory' }; },
  });
  assert.equal(platform.capabilities.pickBodyAnalysisDirectory, true);
  assert.deepEqual(await platform.paths.pickBodyAnalysisDirectory('scalp'), { path: 'selected-directory' });
  assert.deepEqual(calls, ['scalp']);
});

test('a non-Electron native host can implement individual platform capabilities', async () => {
  const calls = [];
  const platform = createPlatformAdapter({
    descriptor: { kind: 'native-test', capabilities: { customTitleBar: true, cameraAccess: false } },
    setTitleBarTheme: async theme => { calls.push(theme); return { applied: true }; },
    requestCameraAccess: async () => { throw new Error('must not be invoked'); },
  });
  assert.equal(platform.kind, 'native-test');
  assert.equal(platform.capabilities.customTitleBar, true);
  assert.equal(platform.capabilities.cameraAccess, false);
  assert.deepEqual(await platform.window.setTitleBarTheme('light'), { applied: true });
  assert.deepEqual(calls, ['light']);
});

test('platform discovery uses only the isolated host contract', () => {
  const original = globalThis.vantagePlatform;
  try {
    globalThis.vantagePlatform = { descriptor: { kind: 'alternative-native' } };
    assert.equal(getPlatformAdapter().kind, 'alternative-native');
    assert.equal(getPlatformAdapter(), getPlatformAdapter());
  } finally {
    globalThis.vantagePlatform = original;
  }
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

const source = readFileSync(new URL('../../preload.cjs', import.meta.url), 'utf8');

test('preload exposes a narrow platform contract and retains the legacy bridge', async () => {
  const exposed = {};
  const invocations = [];
  const descriptor = { kind: 'electron', backend: { baseUrl: 'http://127.0.0.1:8765' } };
  runInNewContext(source, {
    process: { platform: 'linux' },
    require(name) {
      assert.equal(name, 'electron');
      return {
        contextBridge: { exposeInMainWorld: (key, value) => { exposed[key] = value; } },
        ipcRenderer: {
          on() {},
          send() {},
          sendSync: channel => { assert.equal(channel, 'platform:get-descriptor'); return descriptor; },
          invoke: async (...args) => { invocations.push(args); return { ok: true }; },
        },
      };
    },
  });
  assert.equal(exposed.vantagePlatform.descriptor.backend.baseUrl, 'http://127.0.0.1:8765');
  assert.equal(typeof exposed.electronAPI.getSettingsState, 'function');
  assert.equal(Object.hasOwn(exposed.vantagePlatform, 'invoke'), false);
  await exposed.vantagePlatform.requestConfiguration('PUT', '/api/automation/settings', { theme: 'light' });
  await exposed.vantagePlatform.applySavedPreferences();
  await exposed.vantagePlatform.waitUntilBackendReady();
  assert.deepEqual(invocations, [
    ['backend:configuration-request', 'PUT', '/api/automation/settings', { theme: 'light' }],
    ['platform:apply-saved-preferences'],
    ['backend:wait-until-ready'],
  ]);
});

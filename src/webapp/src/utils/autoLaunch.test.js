import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const {
  applyLaunchAtLoginSetting,
  getLaunchAtLoginState,
} = require('./autoLaunch.cjs');

test('getLaunchAtLoginState reads Electron login item state safely', () => {
  const enabled = getLaunchAtLoginState({
    app: {
      getLoginItemSettings: () => ({ openAtLogin: true }),
    },
  });

  assert.equal(enabled, true);
});

test('applyLaunchAtLoginSetting forwards the saved preference to Electron', () => {
  let settingsCall = null;

  const enabled = applyLaunchAtLoginSetting({
    app: {
      setLoginItemSettings: (payload) => {
        settingsCall = payload;
      },
    },
    enabled: true,
  });

  assert.equal(enabled, true);
  assert.deepEqual(settingsCall, {
    openAtLogin: true,
  });
});

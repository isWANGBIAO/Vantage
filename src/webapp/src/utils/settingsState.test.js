import test from 'node:test';
import assert from 'node:assert/strict';

import { loadSettingsState, openSettingsPath, saveSettingsState } from './settingsState.js';

test('loadSettingsState falls back to browser defaults without Electron', async () => {
  const state = await loadSettingsState(undefined);

  assert.equal(state.settings.displayLanguage, 'system');
  assert.equal(state.settings.theme, 'dark');
  assert.equal(state.settings.backgroundMode, 'balanced');
  assert.equal(state.mode, 'browser');
});

test('saveSettingsState forwards payload to Electron settings bridge', async () => {
  const payload = {
    displayLanguage: 'en-US',
    theme: 'light',
    launchAtLogin: true,
    backgroundMode: 'prewarm',
    provider: {
      route: 'cliproxyapi',
      baseUrl: 'https://example.invalid/v1',
      apiKey: 'sk-demo',
      model: 'gpt-5.4',
    },
  };
  let received = null;

  const result = await saveSettingsState(payload, {
    saveSettings: async (submission) => {
      received = submission;
      return {
        settings: {
          displayLanguage: 'en-US',
          theme: 'light',
          launchAtLogin: true,
          backgroundMode: 'prewarm',
        },
      };
    },
  });

  assert.deepEqual(received, payload);
  assert.equal(result.settings.theme, 'light');
});

test('openSettingsPath returns false when no Electron bridge exists', async () => {
  assert.equal(await openSettingsPath('logs', undefined), false);
});

import test from 'node:test';
import assert from 'node:assert/strict';

import { loadSettingsState, openSettingsPath, saveSettingsState } from './settingsState.js';

function createMemoryStorage() {
  const store = new Map();
  return {
    getItem(key) {
      return store.has(key) ? store.get(key) : null;
    },
    setItem(key, value) {
      store.set(key, String(value));
    },
    removeItem(key) {
      store.delete(key);
    },
  };
}

test('loadSettingsState falls back to browser defaults without Electron', async () => {
  const state = await loadSettingsState(undefined);

  assert.equal(state.settings.displayLanguage, 'system');
  assert.equal(state.settings.theme, 'dark');
  assert.equal(state.settings.themeMode, 'dark');
  assert.equal(state.settings.backgroundMode, 'balanced');
  assert.equal(state.settings.voiceBaseUrl, '');
  assert.equal(state.settings.voiceApiKey, '');
  assert.equal(state.settings.voiceModel, 'FunAudioLLM/SenseVoiceSmall');
  assert.equal(state.settings.actionPlanAutoGenerate, true);
  assert.equal(state.mode, 'browser');
});

test('saveSettingsState forwards payload to Electron settings bridge', async () => {
  const payload = {
    displayLanguage: 'en-US',
    theme: 'light',
    themeMode: 'auto',
    launchAtLogin: true,
    backgroundMode: 'prewarm',
    voiceBaseUrl: 'https://voice.example.invalid/v1',
    voiceApiKey: 'sk-voice',
    voiceModel: 'sensevoice',
    actionPlanAutoGenerate: false,
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
          themeMode: 'auto',
          launchAtLogin: true,
          backgroundMode: 'prewarm',
          voiceBaseUrl: 'https://voice.example.invalid/v1',
          voiceApiKey: '********',
          voiceModel: 'sensevoice',
          actionPlanAutoGenerate: false,
        },
      };
    },
  });

  assert.deepEqual(received, payload);
  assert.equal(result.settings.theme, 'light');
  assert.equal(result.settings.themeMode, 'auto');
  assert.equal(result.settings.voiceApiKey, '********');
  assert.equal(result.settings.voiceModel, 'sensevoice');
  assert.equal(result.settings.actionPlanAutoGenerate, false);
});

test('openSettingsPath returns false when no Electron bridge exists', async () => {
  assert.equal(await openSettingsPath('logs', undefined), false);
});

test('browser settings fallback persists to localStorage and returns deep copies', async () => {
  const originalWindow = globalThis.window;
  const originalLocalStorage = globalThis.localStorage;
  const storage = createMemoryStorage();

  globalThis.window = { localStorage: storage };
  globalThis.localStorage = storage;

  try {
    const saved = await saveSettingsState({
      displayLanguage: 'zh-CN',
      theme: 'light',
      themeMode: 'auto',
      launchAtLogin: true,
      backgroundMode: 'power_saver',
      voiceBaseUrl: 'https://voice.example.invalid/v1',
      voiceApiKey: 'sk-voice',
      voiceModel: 'sensevoice',
      actionPlanAutoGenerate: false,
    }, undefined);

    assert.equal(saved.settings.backgroundMode, 'power_saver');

    const loaded = await loadSettingsState(undefined);
    assert.equal(loaded.settings.displayLanguage, 'zh-CN');
    assert.equal(loaded.settings.themeMode, 'auto');
    assert.equal(loaded.settings.backgroundMode, 'power_saver');
    assert.equal(loaded.settings.voiceModel, 'sensevoice');
    assert.equal(loaded.settings.actionPlanAutoGenerate, false);

    loaded.settings.backgroundMode = 'prewarm';
    const loadedAgain = await loadSettingsState(undefined);
    assert.equal(loadedAgain.settings.backgroundMode, 'power_saver');
  } finally {
    globalThis.window = originalWindow;
    globalThis.localStorage = originalLocalStorage;
  }
});

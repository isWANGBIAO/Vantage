import test from 'node:test';
import assert from 'node:assert/strict';
import { loadSettingsState, openSettingsPath, saveSettingsState } from './settingsState.js';
import { createPlatformAdapter } from './platformAdapter.js';

function nativePlatform(requestConfiguration) {
  return createPlatformAdapter({ descriptor: { kind: 'electron' }, requestConfiguration });
}

test('settings adapter translates canonical payloads for every UI without owning persistence', async () => {
  let saved;
  const platform = nativePlatform(async (method, path, payload) => {
    assert.equal(path, '/api/automation/settings');
    if (method === 'PUT') saved = payload;
    return { settings: { theme: 'light', action_plan_check_interval_minutes: 0, voice_api_key: '********', voice_has_api_key: true } };
  });
  const result = await saveSettingsState({ theme: 'light', actionPlanCheckIntervalMinutes: 0, backgroundMode: 'prewarm' }, platform);
  assert.deepEqual(saved, { theme: 'light', action_plan_check_interval_minutes: 0 });
  assert.equal(result.mode, 'electron');
  assert.equal(result.settings.actionPlanCheckIntervalMinutes, 0);
  assert.equal(result.settings.voiceHasApiKey, true);
  assert.equal(Object.hasOwn(result.settings, 'backgroundMode'), false);
});

test('settings read failures reject without returning writable defaults', async () => {
  const backendError = new Error('backend unavailable');
  await assert.rejects(loadSettingsState(nativePlatform(async () => { throw backendError; })), (error) => error === backendError);
});

test('settings mutation failures do not apply native effects or claim success', async () => {
  let applied = false;
  const platform = createPlatformAdapter({
    requestConfiguration: async () => { throw new Error('not saved'); },
    applySavedPreferences: async () => { applied = true; },
  });
  await assert.rejects(saveSettingsState({ theme: 'light' }, platform), /not saved/);
  assert.equal(applied, false);
});

test('opening settings paths is capability-based and unavailable in a browser', async () => {
  assert.equal(await openSettingsPath('logs', createPlatformAdapter()), false);
  const calls = [];
  const platform = createPlatformAdapter({ openSettingsPath: async key => { calls.push(key); return { opened: true }; } });
  assert.equal(await openSettingsPath('logs', platform), true);
  assert.deepEqual(calls, ['logs']);
});

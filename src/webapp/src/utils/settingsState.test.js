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
    assert.equal(path, '/api/v1/settings');
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

test('body-analysis settings round-trip through the shared JSON settings API', async () => {
  let saved;
  const platform = nativePlatform(async (method, path, payload) => {
    assert.equal(path, '/api/v1/settings');
    if (method === 'PUT') saved = payload;
    return { settings: {
      body_analysis_enabled: true,
      body_analysis_leg_dir: 'leg-directory',
      body_analysis_scalp_dir: 'scalp-directory',
      body_analysis_model_dir: 'model-directory',
    } };
  });
  const result = await saveSettingsState({
    bodyAnalysisEnabled: true,
    bodyAnalysisLegDir: 'leg-directory',
    bodyAnalysisScalpDir: 'scalp-directory',
    bodyAnalysisModelDir: 'model-directory',
  }, platform);
  assert.deepEqual(saved, {
    body_analysis_enabled: true,
    body_analysis_leg_dir: 'leg-directory',
    body_analysis_scalp_dir: 'scalp-directory',
    body_analysis_model_dir: 'model-directory',
  });
  assert.equal(result.settings.bodyAnalysisEnabled, true);
  assert.equal(result.settings.bodyAnalysisLegDir, 'leg-directory');
});

test('sleep chart modes round-trip with explicit partial updates and old-server defaults', async () => {
  let settings = {};
  const calls = [];
  const platform = nativePlatform(async (method, _path, payload) => {
    if (method === 'PUT') {
      calls.push(payload);
      settings = { ...settings, ...payload };
    }
    return { settings };
  });
  assert.equal((await loadSettingsState(platform)).settings.sleepChartMode, 'segments');
  for (const mode of ['total', 'segments', 'monthly', 'rolling']) {
    assert.equal((await saveSettingsState({ sleepChartMode: mode }, platform)).settings.sleepChartMode, mode);
    assert.deepEqual(calls.at(-1), { sleep_chart_mode: mode });
  }
  // The general settings form does not edit this preference. Its stale save
  // must omit the field, preserving changes made from the chart meanwhile.
  await saveSettingsState({ theme: 'light', displayLanguage: 'en-US' }, platform);
  assert.deepEqual(calls.at(-1), { theme: 'light', display_language: 'en-US' });
  assert.equal((await loadSettingsState(platform)).settings.sleepChartMode, 'rolling');
});

test('invalid sleep mode submissions are sent to shared backend validation without coercion', async () => {
  let submitted;
  const platform = nativePlatform(async (_method, _path, payload) => {
    submitted = payload;
    throw new Error('sleep_chart_mode rejected');
  });
  await assert.rejects(saveSettingsState({ sleepChartMode: 'weekly' }, platform), /rejected/);
  assert.deepEqual(submitted, { sleep_chart_mode: 'weekly' });
});

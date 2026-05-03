import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const settingsSource = readFileSync(new URL('./Settings.jsx', import.meta.url), 'utf8');

test('Settings exposes the five formal settings sections', () => {
  for (const sectionKey of [
    'settings.section.general',
    'settings.section.ai_provider',
    'settings.section.voice_provider',
    'settings.section.data_logs',
    'settings.section.performance',
    'settings.section.about',
  ]) {
    assert.ok(settingsSource.includes(sectionKey), `${sectionKey} should be defined`);
  }
  assert.ok(settingsSource.includes('t(section.labelKey)'));
});

test('Settings exposes automatic theme mode and independent voice provider controls', () => {
  assert.ok(settingsSource.includes("value: 'auto'"));
  assert.ok(settingsSource.includes('settings.general.theme_auto'));
  assert.ok(settingsSource.includes('themeMode'));
  assert.ok(settingsSource.includes('renderVoiceProvider'));
  assert.ok(settingsSource.includes('voiceBaseUrl'));
  assert.ok(settingsSource.includes('voiceApiKey'));
  assert.ok(settingsSource.includes('voiceModel'));
  assert.ok(settingsSource.includes('voiceProviderMode'));
  assert.ok(settingsSource.includes('voiceModels'));
  assert.ok(settingsSource.includes('settings.voice_provider.base_url'));
  assert.ok(settingsSource.includes('settings.voice_provider.api_key'));
  assert.ok(settingsSource.includes('settings.voice_provider.model'));
  assert.ok(settingsSource.includes('settings.provider.mode.inherit_ai'));
  assert.ok(settingsSource.includes('refreshSpecialProviderModels'));
  assert.ok(settingsSource.includes('/api/provider_models/discover'));
});

test('Settings exposes independent image generation provider controls', () => {
  assert.ok(settingsSource.includes('settings.section.image_provider'));
  assert.ok(settingsSource.includes('renderImageProvider'));
  assert.ok(settingsSource.includes('imageBaseUrl'));
  assert.ok(settingsSource.includes('imageApiKey'));
  assert.ok(settingsSource.includes('imageModel'));
  assert.ok(settingsSource.includes('imageProviderMode'));
  assert.ok(settingsSource.includes('imageModels'));
  assert.ok(settingsSource.includes('settings.image_provider.base_url'));
  assert.ok(settingsSource.includes('settings.image_provider.api_key'));
  assert.ok(settingsSource.includes('settings.image_provider.model'));
  assert.ok(settingsSource.includes('showImageApiKey'));
  assert.ok(settingsSource.includes('settings.provider.mode.custom'));
  assert.ok(settingsSource.includes('settings-provider-model-select'));
});

test('Settings masks provider API key until the user reveals it', () => {
  assert.ok(settingsSource.includes('showApiKey'));
  assert.ok(settingsSource.includes("type={showApiKey ? 'text' : 'password'}"));
  assert.ok(settingsSource.includes('settings.provider.show_key'));
  assert.ok(settingsSource.includes('settings.provider.hide_key'));
});

test('Settings saves provider config and refreshes available LLM models', () => {
  assert.ok(settingsSource.includes('saveSettingsState'));
  assert.ok(settingsSource.includes('/api/llm_models'));
  assert.ok(settingsSource.includes("vantage:llm-models-updated"));
  assert.ok(settingsSource.includes('providerConfig'));
  assert.ok(settingsSource.includes('default_model'));
  assert.ok(settingsSource.includes('backgroundMode'));
});

test('Settings exposes Action Plan startup autogeneration as a performance setting', () => {
  assert.ok(settingsSource.includes('actionPlanAutoGenerate'));
  assert.ok(settingsSource.includes('settings.performance.action_plan_auto_generate'));
  assert.ok(settingsSource.includes('settings.performance.action_plan_auto_generate_hint'));
});

test('Settings renders multi-provider controls and discover refresh', () => {
  assert.ok(settingsSource.includes('addProvider'));
  assert.ok(settingsSource.includes('deleteProvider'));
  assert.ok(settingsSource.includes('setDefaultProvider'));
  assert.ok(settingsSource.includes('toggleProviderEnabled'));
  assert.ok(settingsSource.includes('/api/llm_models/discover'));
  assert.ok(settingsSource.includes('refreshProviderModels'));
  assert.ok(settingsSource.includes('settings-provider-model-select'));
  assert.ok(settingsSource.includes('currentProvider.models'));
  assert.ok(settingsSource.includes('providerRouteDraft'));
  assert.ok(settingsSource.includes('commitProviderRoute'));
  assert.equal(settingsSource.includes('updateProviderRoute'), false);
  assert.equal(settingsSource.includes("onChange={(event) => updateProvider('model', event.target.value)}\n        />"), false);
});

test('Settings uses real select controls for discovered model lists instead of filtered datalists', () => {
  assert.ok(settingsSource.includes('ModelSelectControl'));
  assert.ok(settingsSource.includes('<select'));
  assert.ok(settingsSource.includes('models.length > 0'));
  assert.equal(settingsSource.includes('<datalist'), false);
  assert.equal(settingsSource.includes('list="settings-image-models"'), false);
  assert.equal(settingsSource.includes('list="settings-voice-models"'), false);
});

test('Settings about page shows version build date and commit', () => {
  assert.ok(settingsSource.includes('settings.about.build_date'));
  assert.ok(settingsSource.includes('settings.about.build_commit'));
  assert.ok(settingsSource.includes('state?.app?.buildDate'));
  assert.ok(settingsSource.includes('state?.app?.buildCommit'));
});

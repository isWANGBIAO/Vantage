import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const settingsSource = readFileSync(new URL('./Settings.jsx', import.meta.url), 'utf8');

test('Settings exposes the five formal settings sections', () => {
  for (const sectionKey of [
    'settings.section.general',
    'settings.section.ai_provider',
    'settings.section.data_logs',
    'settings.section.performance',
    'settings.section.about',
  ]) {
    assert.ok(settingsSource.includes(sectionKey), `${sectionKey} should be defined`);
  }
  assert.ok(settingsSource.includes('t(section.labelKey)'));
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
  assert.ok(settingsSource.includes('availableModels'));
  assert.ok(settingsSource.includes('default_model'));
  assert.ok(settingsSource.includes('provider:'));
  assert.ok(settingsSource.includes('backgroundMode'));
});

test('Settings renders provider model as a catalog-backed selector', () => {
  assert.ok(settingsSource.includes('buildModelOptions'));
  assert.ok(settingsSource.includes('settings-provider-model-select'));
  assert.ok(settingsSource.includes('availableModels.map'));
  assert.equal(settingsSource.includes("onChange={(event) => updateProvider('model', event.target.value)}\n        />"), false);
});

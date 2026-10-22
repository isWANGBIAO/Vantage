import test from 'node:test';
import assert from 'node:assert/strict';

import {
  normalizeModelList,
  normalizeProviderModels,
  resolveRefreshedModelSelection,
  resolveInheritedAiProvider,
} from './providerModels.js';

test('voice inheritance resolves saved complete providers and local proxy defaults', () => {
  const config = { selected_provider: 'alpha', providers: {
    alpha: { enabled: true, api_key: '********', base_url: 'https://alpha.invalid/v1' },
    beta: { enabled: true, api_key: '********', base_url: 'https://beta.invalid/v1' },
  } };
  assert.equal(resolveInheritedAiProvider(config).route, 'alpha');
  config.providers.alpha.enabled = false;
  assert.equal(resolveInheritedAiProvider(config).route, 'beta');
  config.providers.beta.api_key = '';
  assert.equal(resolveInheritedAiProvider(config), null);
  assert.equal(resolveInheritedAiProvider({ providers: { custom: { api_key: '********' } } }).base_url, 'http://127.0.0.1:8317/v1');
  assert.equal(resolveInheritedAiProvider(null), null);
});

test('resolveRefreshedModelSelection drops stale selected model when discovery returns a list', () => {
  const selection = resolveRefreshedModelSelection({
    currentModel: 'qwen3vl',
    currentModels: ['qwen3vl', 'qwen3coder'],
    discoveredModels: ['qwen', 'qwen3.5-27b', 'deepseek-chat'],
  });

  assert.deepEqual(selection, {
    model: 'qwen',
    models: ['qwen', 'qwen3.5-27b', 'deepseek-chat'],
  });
});

test('resolveRefreshedModelSelection preserves selected model when provider still reports it', () => {
  const selection = resolveRefreshedModelSelection({
    currentModel: 'gpt-5.5',
    currentModels: ['gpt-5.5', 'gpt-5.4'],
    discoveredModels: ['gpt-5.4', 'gpt-5.5'],
  });

  assert.deepEqual(selection, {
    model: 'gpt-5.5',
    models: ['gpt-5.4', 'gpt-5.5'],
  });
});

test('resolveRefreshedModelSelection keeps current list when discovery returns nothing', () => {
  const selection = resolveRefreshedModelSelection({
    currentModel: 'manual-model',
    currentModels: ['manual-model', 'fallback-model'],
    discoveredModels: [],
  });

  assert.deepEqual(selection, {
    model: 'manual-model',
    models: ['manual-model', 'fallback-model'],
  });
});

test('normalize model helpers deduplicate and keep explicit model first', () => {
  assert.deepEqual(
    normalizeProviderModels({ model: ' qwen ', models: ['qwen', ' deepseek-chat ', '', 'qwen'] }),
    ['qwen', 'deepseek-chat'],
  );
  assert.deepEqual(
    normalizeModelList(['gpt-5.4', 'gpt-5.5'], 'gpt-5.5'),
    ['gpt-5.5', 'gpt-5.4'],
  );
});

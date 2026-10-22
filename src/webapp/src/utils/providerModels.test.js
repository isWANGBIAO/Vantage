import test from 'node:test';
import assert from 'node:assert/strict';

import {
  normalizeModelList,
  normalizeProviderModels,
  resolveRefreshedModelSelection,
  resolveInheritedAiProvider,
} from './providerModels.js';

test('voice inheritance uses authoritative backend metadata instead of JavaScript numeric-key order', () => {
  const config = { selected_provider: 'disabled', providers: {
    disabled: { enabled: false },
    10: { api_key: '********', base_url: 'https://ten.invalid/v1' },
    2: { api_key: '********', base_url: 'https://two.invalid/v1' },
  } };
  assert.deepEqual(Object.keys(config.providers), ['2', '10', 'disabled']);
  assert.equal(resolveInheritedAiProvider({ provider: config, inheritedAiProvider: { route: '10', base_url: 'https://ten.invalid/v1', has_api_key: true } }).route, '10');
  assert.equal(resolveInheritedAiProvider({ provider: config }), null);
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

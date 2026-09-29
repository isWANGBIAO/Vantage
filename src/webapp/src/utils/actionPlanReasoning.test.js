import test from 'node:test';
import assert from 'node:assert/strict';

import {
  ACTION_PLAN_REASONING_OPTIONS,
  ACTION_PLAN_REASONING_STORAGE_KEY,
  buildReasoningOptionsFromTiers,
  getReasoningOptionsForModel,
  getReasoningOptionsForModelContract,
  isDeepSeekV4Model,
  isQwen38Model,
  loadStoredActionPlanReasoningEffort,
  normalizeActionPlanReasoningEffort,
  normalizeReasoningEffortForModel,
  normalizeReasoningEffortForModelContract,
  resolveReasoningEffortFromContract,
  saveActionPlanReasoningEffort,
} from './actionPlanReasoning.js';

function createStorage(initialValue) {
  const state = new Map();
  if (initialValue !== undefined) {
    state.set(ACTION_PLAN_REASONING_STORAGE_KEY, initialValue);
  }

  return {
    getItem(key) {
      return state.has(key) ? state.get(key) : null;
    },
    setItem(key, value) {
      state.set(key, value);
    },
  };
}

test('normalizeActionPlanReasoningEffort defaults to medium', () => {
  assert.equal(normalizeActionPlanReasoningEffort(undefined), 'medium');
  assert.equal(normalizeActionPlanReasoningEffort('invalid'), 'medium');
});

test('loadStoredActionPlanReasoningEffort reads saved value', () => {
  const storage = createStorage('high');
  assert.equal(loadStoredActionPlanReasoningEffort(storage), 'high');
});

test('loadStoredActionPlanReasoningEffort falls back to medium for bad storage values', () => {
  const storage = createStorage('bad');
  assert.equal(loadStoredActionPlanReasoningEffort(storage), 'medium');
});

test('saveActionPlanReasoningEffort stores normalized value', () => {
  const storage = createStorage();
  saveActionPlanReasoningEffort('xhigh', storage);

  assert.equal(
    storage.getItem(ACTION_PLAN_REASONING_STORAGE_KEY),
    'xhigh',
  );

  saveActionPlanReasoningEffort('nope', storage);

  assert.equal(
    storage.getItem(ACTION_PLAN_REASONING_STORAGE_KEY),
    'medium',
  );
});

test('ACTION_PLAN_REASONING_OPTIONS exposes UI labels in display order', () => {
  assert.deepEqual(
    ACTION_PLAN_REASONING_OPTIONS.map((option) => `${option.value}:${option.labelKey}:${option.fallbackLabel}`),
    [
      'low:common.reasoning.low:Low',
      'medium:common.reasoning.medium:Medium',
      'high:common.reasoning.high:High',
      'xhigh:common.reasoning.xhigh:Extra High',
    ],
  );
});

test('getReasoningOptionsForModel exposes only High and Max for DeepSeek V4', () => {
  assert.deepEqual(
    getReasoningOptionsForModel('deepseek-flash').map((option) => `${option.value}:${option.labelKey}:${option.fallbackLabel}`),
    [
      'high:common.reasoning.high:High',
      'max:common.reasoning.max:Max',
    ],
  );
});

test('normalizeReasoningEffortForModel maps GPT and DeepSeek values safely', () => {
  assert.equal(normalizeReasoningEffortForModel('xhigh', 'deepseek-flash'), 'high');
  assert.equal(normalizeReasoningEffortForModel('medium', 'deepseek-flash'), 'high');
  assert.equal(normalizeReasoningEffortForModel('max', 'deepseek-flash'), 'max');
  assert.equal(normalizeReasoningEffortForModel('max', 'gpt-5.5'), 'xhigh');
  assert.equal(normalizeReasoningEffortForModel('low', 'gpt-5.5'), 'low');
});

test('current and legacy DeepSeek Flash names share the reasoning contract', () => {
  for (const model of [
    'deepseek-flash',
    'DeepSeek-Flash',
    'deepseek-flash-vision-exp',
    'deepseek-v4-flash',
    'DeepSeek-V4-Flash-0731',
    'deepseek-ai/DeepSeek-V4-Flash-0731',
  ]) {
    assert.equal(isDeepSeekV4Model(model), true, model);
    assert.deepEqual(
      getReasoningOptionsForModel(model).map((option) => option.value),
      ['high', 'max'],
      model,
    );
    assert.equal(normalizeReasoningEffortForModel('medium', model), 'high', model);
    assert.equal(normalizeReasoningEffortForModel('xhigh', model), 'high', model);
    assert.equal(normalizeReasoningEffortForModel('max', model), 'max', model);
  }
  assert.equal(isDeepSeekV4Model('DeepSeek-V4-Flash-07310'), false);
  assert.equal(isDeepSeekV4Model('deepseek-v4-pro'), false);
  assert.equal(isDeepSeekV4Model('deepseek-chat'), false);
});

test('backend tier contract drives options and resolution', () => {
  // DeepSeek-style: high/max only, with the intentional xhigh -> max remap.
  const deepseekTiers = ['high', 'max'];
  const deepseekAliases = { xhigh: 'max' };
  assert.deepEqual(
    buildReasoningOptionsFromTiers(deepseekTiers).map((option) => `${option.value}:${option.labelKey}`),
    ['high:common.reasoning.high', 'max:common.reasoning.max'],
  );
  assert.equal(resolveReasoningEffortFromContract(deepseekTiers, 'xhigh', deepseekAliases), 'max');
  assert.equal(resolveReasoningEffortFromContract(deepseekTiers, 'xhigh'), 'high');
  assert.equal(resolveReasoningEffortFromContract(deepseekTiers, 'medium', deepseekAliases), 'high');
  assert.equal(resolveReasoningEffortFromContract(deepseekTiers, 'low', deepseekAliases), 'high');
  assert.equal(resolveReasoningEffortFromContract(deepseekTiers, 'max', deepseekAliases), 'max');
  assert.equal(resolveReasoningEffortFromContract(deepseekTiers, 'banana', deepseekAliases), 'high');

  // Qwen-style: high is intentionally remapped up to xhigh.
  const qwenTiers = ['low', 'medium', 'xhigh'];
  assert.equal(resolveReasoningEffortFromContract(qwenTiers, 'high', { high: 'xhigh' }), 'xhigh');
  assert.equal(resolveReasoningEffortFromContract(qwenTiers, 'high'), 'medium');
  assert.equal(resolveReasoningEffortFromContract(qwenTiers, 'xhigh'), 'xhigh');

  // A declared alias wins over clamping even when clamping would go the other way.
  const plainTiers = ['low', 'medium', 'high', 'xhigh'];
  assert.equal(resolveReasoningEffortFromContract(plainTiers, 'high', { high: 'low' }), 'low');
  assert.equal(resolveReasoningEffortFromContract(plainTiers, 'high', { high: 'medium' }), 'medium');

  // An alias pointing at a level the model does not offer is ignored, and the
  // generic ranking rules decide instead. These expectations are verified
  // against the backend resolver for the identical inputs.
  assert.equal(
    resolveReasoningEffortFromContract(['low', 'medium', 'xhigh'], 'high', { high: 'max' }),
    'medium',
  );
  assert.equal(
    resolveReasoningEffortFromContract(['low', 'medium', 'xhigh'], 'xhigh', { xhigh: 'max' }),
    'xhigh',
  );
  assert.equal(
    resolveReasoningEffortFromContract(['low', 'medium', 'xhigh'], 'high', { high: 'xhigh' }),
    'xhigh',
  );
  assert.equal(
    resolveReasoningEffortFromContract(['low', 'medium', 'xhigh'], 'high'),
    'medium',
  );

  // A level the frontend has no copy for is still offered, labelled by value.
  const customTiers = ['low', 'ultra'];
  assert.deepEqual(
    buildReasoningOptionsFromTiers(customTiers).map((option) => `${option.value}:${option.fallbackLabel}`),
    ['low:Low', 'ultra:ultra'],
  );
  assert.equal(resolveReasoningEffortFromContract(customTiers, 'ultra'), 'ultra');

  // Absent contract falls back to the legacy model-name behaviour.
  assert.equal(resolveReasoningEffortFromContract([], 'xhigh'), null);
  assert.equal(resolveReasoningEffortFromContract(undefined, 'xhigh'), null);
  assert.equal(resolveReasoningEffortFromContract(null, 'xhigh'), null);
});

test('contract helpers fall back to model-name rules when tiers are absent', () => {
  assert.deepEqual(
    getReasoningOptionsForModelContract('deepseek-flash', []).map((option) => option.value),
    ['high', 'max'],
  );
  assert.equal(normalizeReasoningEffortForModelContract('medium', 'deepseek-flash', []), 'high');
  assert.equal(normalizeReasoningEffortForModelContract('xhigh', 'deepseek-flash', []), 'high');

  // With a contract present the contract wins, even over the name-based rules.
  assert.equal(
    normalizeReasoningEffortForModelContract('medium', 'deepseek-flash', ['low', 'medium']),
    'medium',
  );
  assert.deepEqual(
    getReasoningOptionsForModelContract('deepseek-flash', ['low', 'medium']).map((o) => o.value),
    ['low', 'medium'],
  );
});

test('Qwen3.8 exposes only supported reasoning levels and maps high to xhigh', () => {
  assert.equal(isQwen38Model('Qwen3.8-27B'), true);
  assert.equal(isQwen38Model('Qwen/Qwen3.8-27B'), true);
  assert.equal(isQwen38Model('Qwen3.6-27B'), false);
  assert.deepEqual(
    getReasoningOptionsForModel('Qwen3.8-27B').map((option) => option.value),
    ['low', 'medium', 'xhigh'],
  );
  assert.equal(
    normalizeReasoningEffortForModel('high', 'Qwen3.8-27B'),
    'xhigh',
  );
  assert.equal(
    normalizeReasoningEffortForModel('medium', 'Qwen/Qwen3.8-27B'),
    'medium',
  );
});

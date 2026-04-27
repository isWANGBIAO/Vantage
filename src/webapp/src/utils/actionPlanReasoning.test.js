import test from 'node:test';
import assert from 'node:assert/strict';

import {
  ACTION_PLAN_REASONING_OPTIONS,
  ACTION_PLAN_REASONING_STORAGE_KEY,
  getReasoningOptionsForModel,
  loadStoredActionPlanReasoningEffort,
  normalizeActionPlanReasoningEffort,
  normalizeReasoningEffortForModel,
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
    getReasoningOptionsForModel('deepseek-v4-pro').map((option) => `${option.value}:${option.labelKey}:${option.fallbackLabel}`),
    [
      'high:common.reasoning.high:High',
      'max:common.reasoning.max:Max',
    ],
  );
});

test('normalizeReasoningEffortForModel maps GPT and DeepSeek values safely', () => {
  assert.equal(normalizeReasoningEffortForModel('xhigh', 'deepseek-v4-flash'), 'max');
  assert.equal(normalizeReasoningEffortForModel('medium', 'deepseek-v4-pro'), 'high');
  assert.equal(normalizeReasoningEffortForModel('max', 'gpt-5.5'), 'xhigh');
  assert.equal(normalizeReasoningEffortForModel('low', 'gpt-5.5'), 'low');
});

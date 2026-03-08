import test from 'node:test';
import assert from 'node:assert/strict';

import {
  ACTION_PLAN_REASONING_OPTIONS,
  ACTION_PLAN_REASONING_STORAGE_KEY,
  loadStoredActionPlanReasoningEffort,
  normalizeActionPlanReasoningEffort,
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
    ACTION_PLAN_REASONING_OPTIONS.map((option) => `${option.value}:${option.label}`),
    [
      'low:Low',
      'medium:Medium',
      'high:High',
      'xhigh:Extra High',
    ],
  );
});

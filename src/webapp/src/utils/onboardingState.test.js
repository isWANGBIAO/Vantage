import test from 'node:test';
import assert from 'node:assert/strict';
import { loadOnboardingState } from './onboardingState.js';

test('loadOnboardingState falls back to completed browser mode when no electron bridge exists', async () => {
  const state = await loadOnboardingState(undefined);

  assert.deepEqual(state, {
    completed: true,
    launchAtLogin: false,
    mode: 'browser',
  });
});

test('loadOnboardingState reflects incomplete onboarding from Electron', async () => {
  const state = await loadOnboardingState({
    getOnboardingState: async () => ({
      completed: false,
      launchAtLogin: true,
    }),
  });

  assert.deepEqual(state, {
    completed: false,
    launchAtLogin: true,
    mode: 'electron',
  });
});

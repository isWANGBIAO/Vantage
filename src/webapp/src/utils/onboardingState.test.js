import test from 'node:test';
import assert from 'node:assert/strict';
import { completeOnboardingSetup, loadOnboardingState, pickLegacyRoot } from './onboardingState.js';

test('loadOnboardingState falls back to completed browser mode when no electron bridge exists', async () => {
  const state = await loadOnboardingState(undefined);

  assert.deepEqual(state, {
    completed: true,
    launchAtLogin: false,
    providerConfigured: false,
    migrationCompleted: false,
    legacyRoot: null,
    mode: 'browser',
  });
});

test('loadOnboardingState reflects incomplete onboarding from Electron', async () => {
  const state = await loadOnboardingState({
    getOnboardingState: async () => ({
      completed: false,
      launchAtLogin: true,
      providerConfigured: true,
      migrationCompleted: true,
      legacyRoot: 'C:\\legacy-root',
    }),
  });

  assert.deepEqual(state, {
    completed: false,
    launchAtLogin: true,
    providerConfigured: true,
    migrationCompleted: true,
    legacyRoot: 'C:\\legacy-root',
    mode: 'electron',
  });
});

test('completeOnboardingSetup forwards the submission payload to Electron', async () => {
  const payload = {
    launchAtLogin: true,
    selectedProvider: 'openai',
    apiKey: 'sk-demo',
    baseUrl: 'https://example.invalid/v1',
    model: 'gpt-5',
    importLegacyData: true,
    legacyRoot: 'C:\\legacy-root',
    skipChatSetup: false,
  };

  let received = null;
  const result = await completeOnboardingSetup(payload, {
    completeOnboarding: async (submission) => {
      received = submission;
      return { completed: true, launchAtLogin: true };
    },
  });

  assert.deepEqual(received, payload);
  assert.deepEqual(result, { completed: true, launchAtLogin: true });
});

test('pickLegacyRoot returns the selected folder path from Electron', async () => {
  const selectedPath = await pickLegacyRoot({
    pickLegacyRoot: async () => ({ path: 'D:\\legacy-history' }),
  });

  assert.equal(selectedPath, 'D:\\legacy-history');
});

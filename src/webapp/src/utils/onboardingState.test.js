import test from 'node:test';
import assert from 'node:assert/strict';
import { completeOnboardingSetup, loadOnboardingState, pickLegacyRoot } from './onboardingState.js';
import { createPlatformAdapter } from './platformAdapter.js';

const nativePlatform = requestConfiguration => createPlatformAdapter({ descriptor: { kind: 'electron' }, requestConfiguration });

test('onboarding reflects the backend state instead of assuming browser setup is complete', async () => {
  const state = await loadOnboardingState(nativePlatform(async () => ({ completed: false, launchAtLogin: true, displayLanguage: 'zh-CN', legacyRoot: '/legacy' })));
  assert.equal(state.completed, false);
  assert.equal(state.launchAtLogin, true);
  assert.equal(state.displayLanguage, 'zh-CN');
  assert.equal(state.legacyRoot, '/legacy');
});

test('onboarding read and write failures reject instead of reporting success', async () => {
  const platform = nativePlatform(async () => { throw new Error('backend unavailable'); });
  await assert.rejects(loadOnboardingState(platform), /backend unavailable/);
  await assert.rejects(completeOnboardingSetup({ skipChatSetup: true }, platform), /backend unavailable/);
});

test('completeOnboardingSetup submits the canonical backend contract', async () => {
  let received;
  const platform = nativePlatform(async (method, path, payload) => {
    received = { method, path, payload };
    return { completed: true, launchAtLogin: true };
  });
  assert.deepEqual(await completeOnboardingSetup({ launchAtLogin: true, skipChatSetup: true }, platform), { completed: true, launchAtLogin: true });
  assert.deepEqual(received, { method: 'POST', path: '/api/automation/onboarding/complete', payload: { launch_at_login: true, skip_chat_setup: true } });
});

test('legacy picker uses a narrow optional platform capability', async () => {
  assert.equal(await pickLegacyRoot(createPlatformAdapter()), null);
  assert.equal(await pickLegacyRoot(createPlatformAdapter({ pickLegacyRoot: async () => ({ path: '/legacy-history' }) })), '/legacy-history');
});

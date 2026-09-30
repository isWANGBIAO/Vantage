import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { createPlatformAdapter } from './platformAdapter.js';
import { loadSettingsState, saveSettingsState } from './settingsState.js';
import { loadOnboardingState, completeOnboardingSetup } from './onboardingState.js';
import { loadDisplayLanguageState, saveDisplayLanguageSetting } from './displayLanguageState.js';
import connectionContract from './backendConnection.cjs';
import nativeTransport from './backendTransport.cjs';

async function withServer(handler, run) {
  const server = createServer(handler);
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  try {
    await run(`http://127.0.0.1:${server.address().port}`);
  } finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
}

test('browser and native configuration adapters use one HTTP state for settings, language, and onboarding', async () => {
  const calls = [];
  let settings = { theme: 'dark', action_plan_auto_generate: false, action_plan_check_interval_minutes: 60, display_language: 'system' };
  let onboarding = { completed: false, launchAtLogin: false };
  await withServer(async (request, response) => {
    let body = '';
    for await (const part of request) body += part;
    const payload = body ? JSON.parse(body) : undefined;
    calls.push({ method: request.method, path: request.url, payload });
    response.setHeader('Content-Type', 'application/json');
    if (request.url === '/api/v1/settings') {
      if (payload) settings = { ...settings, ...payload };
      response.end(JSON.stringify({ settings, provider: { version: 2, providers: {} } }));
    } else if (request.url === '/api/v1/settings/display-language') {
      if (payload) settings = { ...settings, ...payload };
      response.end(JSON.stringify({ display_language: settings.display_language }));
    } else if (request.url === '/api/v1/onboarding') {
      response.end(JSON.stringify(onboarding));
    } else if (request.url === '/api/v1/onboarding/complete') {
      onboarding = { completed: true, launchAtLogin: payload.launch_at_login };
      response.end(JSON.stringify(onboarding));
    } else { response.writeHead(404); response.end('{}'); }
  }, async (baseUrl) => {
    const originalBridge = globalThis.vantagePlatform;
    const originalStorage = globalThis.localStorage;
    let applied = 0;
    const native = createPlatformAdapter({
      descriptor: { kind: 'electron', backend: { baseUrl } },
      requestConfiguration: nativeTransport.createBackendJsonRequester({ connection: connectionContract.resolveBackendConnection({ baseUrl }) }),
      applySavedPreferences: async () => { applied += 1; },
    });
    globalThis.vantagePlatform = { descriptor: { kind: 'browser', backend: { baseUrl } } };
    globalThis.localStorage = {
      getItem() { throw new Error('Business state must not read localStorage'); },
      setItem() { throw new Error('Business state must not write localStorage'); },
    };
    try {
      assert.equal((await loadOnboardingState()).completed, false);
      await saveSettingsState({ theme: 'light', actionPlanCheckIntervalMinutes: 0 });
      const nativeSettings = await loadSettingsState(native);
      assert.equal(nativeSettings.settings.theme, 'light');
      assert.equal(nativeSettings.settings.actionPlanCheckIntervalMinutes, 0);
      assert.equal(nativeSettings.settings.actionPlanAutoGenerate, false);
      await saveSettingsState({ actionPlanCheckIntervalMinutes: 15 }, native);
      assert.equal((await loadSettingsState()).settings.actionPlanCheckIntervalMinutes, 15);
      assert.equal((await loadSettingsState()).settings.theme, 'light');
      await saveDisplayLanguageSetting('zh-CN');
      assert.equal((await loadDisplayLanguageState(native)).displayLanguage, 'zh-CN');
      await saveDisplayLanguageSetting('en-US', native);
      assert.equal((await loadDisplayLanguageState()).displayLanguage, 'en-US');
      await completeOnboardingSetup({ skipChatSetup: true, launchAtLogin: true });
      assert.equal((await loadOnboardingState(native)).completed, true);
      assert.equal(applied, 2);
      assert.deepEqual(calls.find(call => call.path.endsWith('/complete')).payload, { launch_at_login: true, skip_chat_setup: true });
      assert.deepEqual(calls.find(call => call.method === 'PUT').payload, { theme: 'light', action_plan_check_interval_minutes: 0 });
    } finally {
      globalThis.vantagePlatform = originalBridge;
      globalThis.localStorage = originalStorage;
    }
  });
});

test('both configuration transports reject failed writes and redirects without native effects or redirect disclosure', async () => {
  let destinationRequests = 0;
  await withServer((_request, response) => { destinationRequests += 1; response.end('{}'); }, async destination => {
    await withServer((_request, response) => { response.writeHead(307, { Location: destination }); response.end(); }, async baseUrl => {
      const originalBridge = globalThis.vantagePlatform;
      globalThis.vantagePlatform = { descriptor: { kind: 'browser', backend: { baseUrl } } };
      let applied = false;
      const native = createPlatformAdapter({
        requestConfiguration: nativeTransport.createBackendJsonRequester({ connection: connectionContract.resolveBackendConnection({ baseUrl }) }),
        applySavedPreferences: async () => { applied = true; },
      });
      try {
        await assert.rejects(saveSettingsState({ voiceApiKey: 'synthetic-test-key' }));
        await assert.rejects(saveSettingsState({ voiceApiKey: 'synthetic-test-key' }, native), /307/);
        await assert.rejects(completeOnboardingSetup({ skipChatSetup: true }));
        await assert.rejects(saveDisplayLanguageSetting('zh-CN'));
        assert.equal(destinationRequests, 0);
        assert.equal(applied, false);
      } finally { globalThis.vantagePlatform = originalBridge; }
    });
  });
});

test('malformed backend responses cannot turn into writable defaults or apparent completion', async () => {
  let applied = false;
  const platform = createPlatformAdapter({
    requestConfiguration: async () => ({}),
    applySavedPreferences: async () => { applied = true; },
  });
  await assert.rejects(loadSettingsState(platform), /invalid settings state/);
  await assert.rejects(saveSettingsState({}, platform), /invalid settings state/);
  await assert.rejects(loadOnboardingState(platform), /invalid onboarding state/);
  await assert.rejects(completeOnboardingSetup({ skipChatSetup: true }, platform), /invalid onboarding state/);
  await assert.rejects(loadDisplayLanguageState(platform), /invalid display language/);
  await assert.rejects(saveDisplayLanguageSetting('zh-CN', platform), /invalid display language/);
  assert.equal(applied, false);
});

import { fetchBackendJson } from './backendRequest.js';
import { getPlatformAdapter } from './platformAdapter.js';
import protocol from './configurationProtocol.cjs';

const { fromBackendSettings, toBackendSettingsPayload, mapPayloadFields, ONBOARDING_PAYLOAD_FIELDS } = protocol;

async function requestConfiguration(method, path, payload, platform) {
  // Native and browser transports send the identical canonical DTO. Neither
  // owns state; validation and persistence are backend responsibilities.
  if (platform.backend.requestJson) {
    return platform.backend.requestJson(method, path, payload);
  }
  return fetchBackendJson(path, {
    method,
    retryPolicy: method === 'GET' ? 'load' : 'mutation',
    ...(payload === undefined ? {} : {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  });
}

async function settingsView(payload, platform) {
  return fromBackendSettings(payload, {
    mode: platform.kind,
    app: platform.app,
    systemLocale: await platform.locale.getSystemLocale(),
  });
}

export async function readSettings(platform = getPlatformAdapter()) {
  return settingsView(await requestConfiguration('GET', '/api/v1/settings', undefined, platform), platform);
}

export async function updateSettings(submission, platform = getPlatformAdapter()) {
  const payload = await requestConfiguration('PUT', '/api/v1/settings', toBackendSettingsPayload(submission), platform);
  const state = await settingsView(payload, platform);
  await platform.preferences.applySaved();
  return state;
}

function validateOnboarding(result) {
  if (!result || typeof result.completed !== 'boolean') {
    throw new TypeError('Vantage backend returned an invalid onboarding state.');
  }
  return result;
}

function validateDisplayLanguage(result) {
  if (!['system', 'zh-CN', 'en-US'].includes(result?.display_language)) {
    throw new TypeError('Vantage backend returned an invalid display language state.');
  }
  return result;
}

export async function readOnboarding(platform = getPlatformAdapter()) {
  return validateOnboarding(await requestConfiguration('GET', '/api/v1/onboarding', undefined, platform));
}

export async function finishOnboarding(submission, platform = getPlatformAdapter()) {
  const result = await requestConfiguration('POST', '/api/v1/onboarding/complete', mapPayloadFields(submission, ONBOARDING_PAYLOAD_FIELDS), platform);
  if (!validateOnboarding(result).completed) throw new Error('Vantage onboarding was not completed.');
  await platform.preferences.applySaved();
  return result;
}

export async function readDisplayLanguage(platform = getPlatformAdapter()) {
  const result = await requestConfiguration('GET', '/api/v1/settings/display-language', undefined, platform);
  validateDisplayLanguage(result);
  return { displayLanguage: result.display_language, systemLocale: await platform.locale.getSystemLocale(), mode: platform.kind };
}

export async function updateDisplayLanguage(displayLanguage, platform = getPlatformAdapter()) {
  const result = await requestConfiguration('PUT', '/api/v1/settings/display-language', { display_language: displayLanguage }, platform);
  validateDisplayLanguage(result);
  await platform.preferences.applySaved();
  return { displayLanguage: result.display_language, systemLocale: await platform.locale.getSystemLocale(), mode: platform.kind };
}

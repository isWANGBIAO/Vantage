import { readOnboarding, finishOnboarding } from './configurationClient.js';
import { getPlatformAdapter } from './platformAdapter.js';

const DEFAULT_ONBOARDING_STATE = {
  completed: false,
  launchAtLogin: false,
  displayLanguage: 'system',
  providerConfigured: false,
  migrationCompleted: false,
  legacyRoot: null,
  mode: 'browser',
};

function normalizeOptionalString(value) {
  if (typeof value !== 'string') {
    return null;
  }
  const normalized = value.trim();
  return normalized || null;
}

function sanitizeOnboardingState(payload, mode) {
  const safePayload = payload && typeof payload === 'object' ? payload : {};
  return {
    completed:
      typeof safePayload.completed === 'boolean'
        ? safePayload.completed
        : DEFAULT_ONBOARDING_STATE.completed,
    launchAtLogin:
      typeof safePayload.launchAtLogin === 'boolean'
        ? safePayload.launchAtLogin
        : DEFAULT_ONBOARDING_STATE.launchAtLogin,
    displayLanguage:
      typeof safePayload.displayLanguage === 'string'
        ? safePayload.displayLanguage
        : DEFAULT_ONBOARDING_STATE.displayLanguage,
    providerConfigured:
      typeof safePayload.providerConfigured === 'boolean'
        ? safePayload.providerConfigured
        : DEFAULT_ONBOARDING_STATE.providerConfigured,
    migrationCompleted:
      typeof safePayload.migrationCompleted === 'boolean'
        ? safePayload.migrationCompleted
        : DEFAULT_ONBOARDING_STATE.migrationCompleted,
    legacyRoot: normalizeOptionalString(safePayload.legacyRoot),
    mode,
  };
}

export async function loadOnboardingState(platform = getPlatformAdapter()) {
  const payload = await readOnboarding(platform);
  return sanitizeOnboardingState(payload, platform.kind);
}

export function completeOnboardingSetup(submission, platform = getPlatformAdapter()) {
  return finishOnboarding(submission, platform);
}

export async function pickLegacyRoot(platform = getPlatformAdapter()) {
  try {
    const payload = await platform.paths.pickLegacyRoot();
    return normalizeOptionalString(payload?.path);
  } catch (error) {
    console.warn('Failed to open legacy history picker.', error);
    return null;
  }
}

export { DEFAULT_ONBOARDING_STATE };

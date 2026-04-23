const DEFAULT_ONBOARDING_STATE = {
  completed: true,
  launchAtLogin: false,
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

function resolveElectronAPI(electronAPI) {
  return electronAPI ?? globalThis.window?.electronAPI ?? globalThis.electronAPI;
}

export async function loadOnboardingState(electronAPI) {
  const resolvedElectronAPI = resolveElectronAPI(electronAPI);
  if (!resolvedElectronAPI?.getOnboardingState) {
    return { ...DEFAULT_ONBOARDING_STATE };
  }

  try {
    const payload = await resolvedElectronAPI.getOnboardingState();
    return sanitizeOnboardingState(payload, 'electron');
  } catch (error) {
    console.warn('Failed to load onboarding state from Electron bridge.', error);
    return { ...DEFAULT_ONBOARDING_STATE };
  }
}

export async function completeOnboardingSetup(submission, electronAPI) {
  const resolvedElectronAPI = resolveElectronAPI(electronAPI);
  if (!resolvedElectronAPI?.completeOnboarding) {
    return {
      completed: true,
      launchAtLogin: Boolean(submission?.launchAtLogin),
    };
  }
  return resolvedElectronAPI.completeOnboarding(submission);
}

export async function pickLegacyRoot(electronAPI) {
  const resolvedElectronAPI = resolveElectronAPI(electronAPI);
  if (!resolvedElectronAPI?.pickLegacyRoot) {
    return null;
  }

  try {
    const payload = await resolvedElectronAPI.pickLegacyRoot();
    return normalizeOptionalString(payload?.path);
  } catch (error) {
    console.warn('Failed to open legacy history picker.', error);
    return null;
  }
}

export { DEFAULT_ONBOARDING_STATE };

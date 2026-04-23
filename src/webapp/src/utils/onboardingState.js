const DEFAULT_ONBOARDING_STATE = {
  completed: true,
  launchAtLogin: false,
  mode: 'browser',
};

function sanitizeOnboardingState(payload, mode) {
  const safePayload = payload && typeof payload === 'object' ? payload : {};
  return {
    completed: typeof safePayload.completed === 'boolean' ? safePayload.completed : DEFAULT_ONBOARDING_STATE.completed,
    launchAtLogin:
      typeof safePayload.launchAtLogin === 'boolean'
        ? safePayload.launchAtLogin
        : DEFAULT_ONBOARDING_STATE.launchAtLogin,
    mode,
  };
}

export async function loadOnboardingState(electronAPI = globalThis.window?.electronAPI ?? globalThis.electronAPI) {
  if (!electronAPI?.getOnboardingState) {
    return { ...DEFAULT_ONBOARDING_STATE };
  }

  try {
    const payload = await electronAPI.getOnboardingState();
    return sanitizeOnboardingState(payload, 'electron');
  } catch (error) {
    console.warn('Failed to load onboarding state from Electron bridge.', error);
    return { ...DEFAULT_ONBOARDING_STATE };
  }
}

export { DEFAULT_ONBOARDING_STATE };

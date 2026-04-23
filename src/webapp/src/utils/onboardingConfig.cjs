const fs = require('fs');
const path = require('path');

const DEFAULT_SETTINGS = {
  version: 1,
  onboarding_completed: false,
  launch_at_login: false,
};

function getSettingsFile(runtimePaths) {
  return path.join(runtimePaths.configDir, 'settings.json');
}

function sanitizeSettings(payload) {
  const safePayload = payload && typeof payload === 'object' ? payload : {};
  return {
    version: 1,
    onboarding_completed:
      typeof safePayload.onboarding_completed === 'boolean'
        ? safePayload.onboarding_completed
        : DEFAULT_SETTINGS.onboarding_completed,
    launch_at_login:
      typeof safePayload.launch_at_login === 'boolean'
        ? safePayload.launch_at_login
        : DEFAULT_SETTINGS.launch_at_login,
  };
}

function loadSettings(runtimePaths) {
  const settingsFile = getSettingsFile(runtimePaths);
  if (!fs.existsSync(settingsFile)) {
    return { ...DEFAULT_SETTINGS };
  }

  try {
    const raw = fs.readFileSync(settingsFile, 'utf8');
    return sanitizeSettings(JSON.parse(raw));
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

function getOnboardingState({ runtimePaths }) {
  const settings = loadSettings(runtimePaths);
  return {
    completed: settings.onboarding_completed,
    launchAtLogin: settings.launch_at_login,
  };
}

module.exports = {
  DEFAULT_SETTINGS,
  getOnboardingState,
  getSettingsFile,
  loadSettings,
  sanitizeSettings,
};

const DEFAULT_SETTINGS_STATE = {
  mode: 'browser',
  settings: {
    displayLanguage: 'system',
    theme: 'dark',
    launchAtLogin: false,
    backgroundMode: 'balanced',
  },
  provider: {
    version: 2,
    selected_provider: null,
    providers: {},
  },
  runtimePaths: {},
  migration: {
    completed: false,
    sourcePath: null,
    importedAt: null,
  },
  app: {
    version: '0.0.0',
    mode: 'browser',
    backendRuntimePath: null,
    dataDir: null,
  },
  systemLocale: 'en-US',
};

function resolveElectronAPI(electronAPI) {
  return electronAPI ?? globalThis.window?.electronAPI ?? globalThis.electronAPI;
}

function normalizeSettings(payload, mode) {
  const safePayload = payload && typeof payload === 'object' ? payload : {};
  const safeSettings = safePayload.settings && typeof safePayload.settings === 'object'
    ? safePayload.settings
    : {};

  return {
    ...DEFAULT_SETTINGS_STATE,
    ...safePayload,
    mode,
    settings: {
      ...DEFAULT_SETTINGS_STATE.settings,
      displayLanguage:
        typeof safeSettings.displayLanguage === 'string'
          ? safeSettings.displayLanguage
          : DEFAULT_SETTINGS_STATE.settings.displayLanguage,
      theme: safeSettings.theme === 'light' ? 'light' : DEFAULT_SETTINGS_STATE.settings.theme,
      launchAtLogin:
        typeof safeSettings.launchAtLogin === 'boolean'
          ? safeSettings.launchAtLogin
          : DEFAULT_SETTINGS_STATE.settings.launchAtLogin,
      backgroundMode:
        ['balanced', 'prewarm', 'power_saver'].includes(safeSettings.backgroundMode)
          ? safeSettings.backgroundMode
          : DEFAULT_SETTINGS_STATE.settings.backgroundMode,
    },
    provider:
      safePayload.provider && typeof safePayload.provider === 'object'
        ? safePayload.provider
        : DEFAULT_SETTINGS_STATE.provider,
    runtimePaths:
      safePayload.runtimePaths && typeof safePayload.runtimePaths === 'object'
        ? safePayload.runtimePaths
        : DEFAULT_SETTINGS_STATE.runtimePaths,
    migration:
      safePayload.migration && typeof safePayload.migration === 'object'
        ? { ...DEFAULT_SETTINGS_STATE.migration, ...safePayload.migration }
        : DEFAULT_SETTINGS_STATE.migration,
    app:
      safePayload.app && typeof safePayload.app === 'object'
        ? { ...DEFAULT_SETTINGS_STATE.app, ...safePayload.app }
        : DEFAULT_SETTINGS_STATE.app,
    systemLocale:
      typeof safePayload.systemLocale === 'string'
        ? safePayload.systemLocale
        : DEFAULT_SETTINGS_STATE.systemLocale,
  };
}

export async function loadSettingsState(electronAPI) {
  const resolvedElectronAPI = resolveElectronAPI(electronAPI);
  if (!resolvedElectronAPI?.getSettingsState) {
    return { ...DEFAULT_SETTINGS_STATE };
  }

  try {
    const payload = await resolvedElectronAPI.getSettingsState();
    return normalizeSettings(payload, 'electron');
  } catch (error) {
    console.warn('Failed to load settings state from Electron bridge.', error);
    return { ...DEFAULT_SETTINGS_STATE };
  }
}

export async function saveSettingsState(submission, electronAPI) {
  const resolvedElectronAPI = resolveElectronAPI(electronAPI);
  if (!resolvedElectronAPI?.saveSettings) {
    return normalizeSettings(
      {
        settings: {
          displayLanguage: submission?.displayLanguage,
          theme: submission?.theme,
          launchAtLogin: Boolean(submission?.launchAtLogin),
          backgroundMode: submission?.backgroundMode,
        },
      },
      'browser',
    );
  }

  const payload = await resolvedElectronAPI.saveSettings(submission);
  return normalizeSettings(payload, 'electron');
}

export async function openSettingsPath(pathKey, electronAPI) {
  const resolvedElectronAPI = resolveElectronAPI(electronAPI);
  if (!resolvedElectronAPI?.openSettingsPath) {
    return false;
  }

  try {
    const result = await resolvedElectronAPI.openSettingsPath(pathKey);
    return Boolean(result?.opened);
  } catch (error) {
    console.warn('Failed to open settings path.', error);
    return false;
  }
}

export { DEFAULT_SETTINGS_STATE };

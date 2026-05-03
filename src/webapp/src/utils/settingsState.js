const DEFAULT_SETTINGS_STATE = {
  mode: 'browser',
  settings: {
    displayLanguage: 'system',
    theme: 'dark',
    themeMode: 'dark',
    launchAtLogin: false,
    backgroundMode: 'balanced',
    voiceBaseUrl: '',
    voiceApiKey: '',
    voiceHasApiKey: false,
    voiceModel: 'FunAudioLLM/SenseVoiceSmall',
    imageBaseUrl: '',
    imageApiKey: '',
    imageHasApiKey: false,
    imageModel: '',
    actionPlanAutoGenerate: true,
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

const BROWSER_SETTINGS_STORAGE_KEY = 'vantage.settingsState';

function cloneSettingsState(value) {
  return JSON.parse(JSON.stringify(value));
}

function resolveElectronAPI(electronAPI) {
  return electronAPI ?? globalThis.window?.electronAPI ?? globalThis.electronAPI;
}

function resolveBrowserStorage() {
  return globalThis.window?.localStorage ?? globalThis.localStorage ?? null;
}

function normalizeSettings(payload, mode) {
  const defaults = cloneSettingsState(DEFAULT_SETTINGS_STATE);
  const safePayload = payload && typeof payload === 'object' ? payload : {};
  const safeSettings = safePayload.settings && typeof safePayload.settings === 'object'
    ? safePayload.settings
    : {};

  return {
    ...defaults,
    ...safePayload,
    mode,
    settings: {
      ...defaults.settings,
      displayLanguage:
        typeof safeSettings.displayLanguage === 'string'
          ? safeSettings.displayLanguage
          : defaults.settings.displayLanguage,
      theme: safeSettings.theme === 'light' ? 'light' : defaults.settings.theme,
      themeMode:
        ['auto', 'dark', 'light'].includes(safeSettings.themeMode)
          ? safeSettings.themeMode
          : (safeSettings.theme === 'light' ? 'light' : defaults.settings.themeMode),
      launchAtLogin:
        typeof safeSettings.launchAtLogin === 'boolean'
          ? safeSettings.launchAtLogin
          : defaults.settings.launchAtLogin,
      backgroundMode:
        ['balanced', 'prewarm', 'power_saver'].includes(safeSettings.backgroundMode)
          ? safeSettings.backgroundMode
          : defaults.settings.backgroundMode,
      voiceBaseUrl:
        typeof safeSettings.voiceBaseUrl === 'string'
          ? safeSettings.voiceBaseUrl
          : defaults.settings.voiceBaseUrl,
      voiceApiKey:
        typeof safeSettings.voiceApiKey === 'string'
          ? safeSettings.voiceApiKey
          : defaults.settings.voiceApiKey,
      voiceHasApiKey:
        typeof safeSettings.voiceHasApiKey === 'boolean'
          ? safeSettings.voiceHasApiKey
          : Boolean(safeSettings.voiceApiKey),
      voiceModel:
        typeof safeSettings.voiceModel === 'string' && safeSettings.voiceModel.trim()
          ? safeSettings.voiceModel
          : defaults.settings.voiceModel,
      imageBaseUrl:
        typeof safeSettings.imageBaseUrl === 'string'
          ? safeSettings.imageBaseUrl
          : defaults.settings.imageBaseUrl,
      imageApiKey:
        typeof safeSettings.imageApiKey === 'string'
          ? safeSettings.imageApiKey
          : defaults.settings.imageApiKey,
      imageHasApiKey:
        typeof safeSettings.imageHasApiKey === 'boolean'
          ? safeSettings.imageHasApiKey
          : Boolean(safeSettings.imageApiKey),
      imageModel:
        typeof safeSettings.imageModel === 'string'
          ? safeSettings.imageModel
          : defaults.settings.imageModel,
      actionPlanAutoGenerate:
        typeof safeSettings.actionPlanAutoGenerate === 'boolean'
          ? safeSettings.actionPlanAutoGenerate
          : defaults.settings.actionPlanAutoGenerate,
    },
    provider:
      safePayload.provider && typeof safePayload.provider === 'object'
        ? cloneSettingsState(safePayload.provider)
        : defaults.provider,
    runtimePaths:
      safePayload.runtimePaths && typeof safePayload.runtimePaths === 'object'
        ? cloneSettingsState(safePayload.runtimePaths)
        : defaults.runtimePaths,
    migration:
      safePayload.migration && typeof safePayload.migration === 'object'
        ? { ...defaults.migration, ...safePayload.migration }
        : defaults.migration,
    app:
      safePayload.app && typeof safePayload.app === 'object'
        ? { ...defaults.app, ...safePayload.app }
        : defaults.app,
    systemLocale:
      typeof safePayload.systemLocale === 'string'
        ? safePayload.systemLocale
        : defaults.systemLocale,
  };
}

export async function loadSettingsState(electronAPI) {
  const resolvedElectronAPI = resolveElectronAPI(electronAPI);
  if (!resolvedElectronAPI?.getSettingsState) {
    const storage = resolveBrowserStorage();
    const stored = storage?.getItem?.(BROWSER_SETTINGS_STORAGE_KEY);
    if (stored) {
      try {
        return normalizeSettings(JSON.parse(stored), 'browser');
      } catch (error) {
        console.warn('Failed to parse browser settings state.', error);
      }
    }
    return cloneSettingsState(DEFAULT_SETTINGS_STATE);
  }

  try {
    const payload = await resolvedElectronAPI.getSettingsState();
    return normalizeSettings(payload, 'electron');
  } catch (error) {
    console.warn('Failed to load settings state from Electron bridge.', error);
    return cloneSettingsState(DEFAULT_SETTINGS_STATE);
  }
}

export async function saveSettingsState(submission, electronAPI) {
  const resolvedElectronAPI = resolveElectronAPI(electronAPI);
  if (!resolvedElectronAPI?.saveSettings) {
    const normalized = normalizeSettings(
      {
        settings: {
          displayLanguage: submission?.displayLanguage,
          theme: submission?.theme,
          themeMode: submission?.themeMode,
          launchAtLogin: Boolean(submission?.launchAtLogin),
          backgroundMode: submission?.backgroundMode,
          voiceBaseUrl: submission?.voiceBaseUrl,
          voiceApiKey: submission?.voiceApiKey,
          voiceHasApiKey: Boolean(submission?.voiceApiKey),
          voiceModel: submission?.voiceModel,
          imageBaseUrl: submission?.imageBaseUrl,
          imageApiKey: submission?.imageApiKey,
          imageHasApiKey: Boolean(submission?.imageApiKey),
          imageModel: submission?.imageModel,
          actionPlanAutoGenerate:
            typeof submission?.actionPlanAutoGenerate === 'boolean'
              ? submission.actionPlanAutoGenerate
              : DEFAULT_SETTINGS_STATE.settings.actionPlanAutoGenerate,
        },
      },
      'browser',
    );
    const storage = resolveBrowserStorage();
    storage?.setItem?.(BROWSER_SETTINGS_STORAGE_KEY, JSON.stringify(normalized));
    return normalized;
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

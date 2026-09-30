import { readSettings, updateSettings } from './configurationClient.js';
import { getPlatformAdapter } from './platformAdapter.js';
import automationLimits from './automationLimits.cjs';

const { MAX_ACTION_PLAN_CHECK_INTERVAL_MINUTES } = automationLimits;

const DEFAULT_SETTINGS_STATE = {
  mode: 'browser',
  settings: {
    displayLanguage: 'system',
    theme: 'dark',
    themeMode: 'dark',
    launchAtLogin: false,
    voiceProviderMode: 'inherit_ai',
    voiceBaseUrl: '',
    voiceApiKey: '',
    voiceHasApiKey: false,
    voiceModel: 'FunAudioLLM/SenseVoiceSmall',
    voiceModels: ['FunAudioLLM/SenseVoiceSmall'],
    voiceLastRefreshedAt: null,
    imageProviderMode: 'inherit_ai',
    imageBaseUrl: '',
    imageApiKey: '',
    imageHasApiKey: false,
    imageModel: '',
    imageModels: [],
    imageLastRefreshedAt: null,
    actionPlanAutoGenerate: true,
    actionPlanCheckIntervalMinutes: 60,
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
    buildDate: null,
    buildCommit: null,
    mode: 'browser',
    backendRuntimePath: null,
    dataDir: null,
  },
  systemLocale: 'en-US',
};

function cloneSettingsState(value) {
  return JSON.parse(JSON.stringify(value));
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
      voiceProviderMode:
        safeSettings.voiceProviderMode === 'custom' ? 'custom' : defaults.settings.voiceProviderMode,
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
      voiceModels:
        Array.isArray(safeSettings.voiceModels)
          ? [...new Set(safeSettings.voiceModels.filter((item) => typeof item === 'string' && item.trim()).map((item) => item.trim()))]
          : defaults.settings.voiceModels,
      voiceLastRefreshedAt:
        typeof safeSettings.voiceLastRefreshedAt === 'string'
          ? safeSettings.voiceLastRefreshedAt
          : null,
      imageProviderMode:
        safeSettings.imageProviderMode === 'custom' ? 'custom' : defaults.settings.imageProviderMode,
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
      imageModels:
        Array.isArray(safeSettings.imageModels)
          ? [...new Set(safeSettings.imageModels.filter((item) => typeof item === 'string' && item.trim()).map((item) => item.trim()))]
          : defaults.settings.imageModels,
      imageLastRefreshedAt:
        typeof safeSettings.imageLastRefreshedAt === 'string'
          ? safeSettings.imageLastRefreshedAt
          : null,
      actionPlanAutoGenerate:
        typeof safeSettings.actionPlanAutoGenerate === 'boolean'
          ? safeSettings.actionPlanAutoGenerate
          : defaults.settings.actionPlanAutoGenerate,
      actionPlanCheckIntervalMinutes: Number.isSafeInteger(safeSettings.actionPlanCheckIntervalMinutes)
        && safeSettings.actionPlanCheckIntervalMinutes >= 0
        && safeSettings.actionPlanCheckIntervalMinutes <= MAX_ACTION_PLAN_CHECK_INTERVAL_MINUTES
        ? safeSettings.actionPlanCheckIntervalMinutes : 60,
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
        ? {
          ...defaults.app,
          ...safePayload.app,
          buildDate:
            typeof safePayload.app.buildDate === 'string'
              ? safePayload.app.buildDate
              : null,
          buildCommit:
            typeof safePayload.app.buildCommit === 'string'
              ? safePayload.app.buildCommit
              : null,
        }
        : defaults.app,
    systemLocale:
      typeof safePayload.systemLocale === 'string'
        ? safePayload.systemLocale
        : defaults.systemLocale,
  };
}

export async function loadSettingsState(platform = getPlatformAdapter()) {
  return normalizeSettings(await readSettings(platform), platform.kind);
}

export async function saveSettingsState(submission, platform = getPlatformAdapter()) {
  return normalizeSettings(await updateSettings(submission, platform), platform.kind);
}

export async function openSettingsPath(pathKey, platform = getPlatformAdapter()) {
  try {
    const result = await platform.paths.openSettingsPath(pathKey);
    return Boolean(result?.opened);
  } catch (error) {
    console.warn('Failed to open settings path.', error);
    return false;
  }
}

export { DEFAULT_SETTINGS_STATE };

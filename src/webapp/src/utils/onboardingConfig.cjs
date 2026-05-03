const fs = require('fs');
const path = require('path');

const DEFAULT_SETTINGS = {
  version: 1,
  onboarding_completed: false,
  launch_at_login: false,
  display_language: 'system',
  theme: 'dark',
  theme_mode: 'dark',
  background_mode: 'balanced',
  action_plan_auto_generate: true,
  voice_provider_mode: 'inherit_ai',
  voice_base_url: '',
  voice_api_key: '',
  voice_model: 'FunAudioLLM/SenseVoiceSmall',
  voice_models: ['FunAudioLLM/SenseVoiceSmall'],
  voice_last_refreshed_at: null,
  image_provider_mode: 'inherit_ai',
  image_base_url: '',
  image_api_key: '',
  image_model: '',
  image_models: [],
  image_last_refreshed_at: null,
};

const PROVIDER_CONFIG_VERSION = 2;
const PROVIDER_TYPE_OPENAI_COMPATIBLE = 'openai-compatible';
const DEFAULT_LOCAL_PROXY_BASE_URL = 'http://127.0.0.1:8317/v1';
const LOCAL_PROXY_PROVIDER_ROUTES = new Set([
  'custom',
  'cliproxyapi',
  'cliproxyapi_primary',
  'local',
  'local_proxy',
]);

const DEFAULT_PROVIDER_CONFIG = {
  version: PROVIDER_CONFIG_VERSION,
  selected_provider: null,
  providers: {},
};

const DEFAULT_MIGRATION_STATE = {
  version: 1,
  completed: false,
  source_path: null,
  imported_at: null,
};

function ensureDir(targetDir) {
  fs.mkdirSync(targetDir, { recursive: true });
}

function getSettingsFile(runtimePaths) {
  ensureDir(runtimePaths.configDir);
  return path.join(runtimePaths.configDir, 'settings.json');
}

function getProvidersFile(runtimePaths) {
  ensureDir(runtimePaths.configDir);
  return path.join(runtimePaths.configDir, 'providers.json');
}

function getMigrationStateFile(runtimePaths) {
  ensureDir(runtimePaths.migrationDir);
  return path.join(runtimePaths.migrationDir, 'migration-state.json');
}

function readJsonFile(filePath) {
  if (!fs.existsSync(filePath)) {
    return null;
  }

  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch {
    return null;
  }
}

function writeJsonFile(filePath, payload) {
  ensureDir(path.dirname(filePath));
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2), 'utf8');
  return payload;
}

function normalizeOptionalString(value) {
  if (typeof value !== 'string') {
    return null;
  }
  const normalized = value.trim();
  return normalized || null;
}

function normalizeProviderType(value) {
  return value === PROVIDER_TYPE_OPENAI_COMPATIBLE
    ? value
    : PROVIDER_TYPE_OPENAI_COMPATIBLE;
}

function sanitizeDisplayLanguage(value) {
  return value === 'zh-CN' || value === 'en-US' || value === 'system'
    ? value
    : DEFAULT_SETTINGS.display_language;
}

function sanitizeTheme(value) {
  return value === 'dark' || value === 'light' ? value : DEFAULT_SETTINGS.theme;
}

function sanitizeThemeMode(value, fallbackTheme = DEFAULT_SETTINGS.theme) {
  if (value === 'auto' || value === 'dark' || value === 'light') {
    return value;
  }
  return sanitizeTheme(fallbackTheme);
}

function sanitizeBackgroundMode(value) {
  return value === 'balanced' || value === 'prewarm' || value === 'power_saver'
    ? value
    : DEFAULT_SETTINGS.background_mode;
}

function sanitizeSpecialProviderMode(value, safePayload, prefix) {
  if (value === 'custom' || value === 'inherit_ai') {
    return value;
  }
  if (
    normalizeOptionalString(safePayload?.[`${prefix}_base_url`])
    || normalizeOptionalString(safePayload?.[`${prefix}_api_key`])
  ) {
    return 'custom';
  }
  return 'inherit_ai';
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
    display_language: sanitizeDisplayLanguage(safePayload.display_language),
    theme: sanitizeTheme(safePayload.theme),
    theme_mode: sanitizeThemeMode(safePayload.theme_mode, safePayload.theme),
    background_mode: sanitizeBackgroundMode(safePayload.background_mode),
    action_plan_auto_generate:
      typeof safePayload.action_plan_auto_generate === 'boolean'
        ? safePayload.action_plan_auto_generate
        : DEFAULT_SETTINGS.action_plan_auto_generate,
    voice_provider_mode: sanitizeSpecialProviderMode(safePayload.voice_provider_mode, safePayload, 'voice'),
    voice_base_url: normalizeOptionalString(safePayload.voice_base_url) || '',
    voice_api_key: normalizeOptionalString(safePayload.voice_api_key) || '',
    voice_model: normalizeOptionalString(safePayload.voice_model) || DEFAULT_SETTINGS.voice_model,
    voice_models: normalizeModels(safePayload.voice_models, safePayload.voice_model || DEFAULT_SETTINGS.voice_model),
    voice_last_refreshed_at: normalizeOptionalString(safePayload.voice_last_refreshed_at),
    image_provider_mode: sanitizeSpecialProviderMode(safePayload.image_provider_mode, safePayload, 'image'),
    image_base_url: normalizeOptionalString(safePayload.image_base_url) || '',
    image_api_key: normalizeOptionalString(safePayload.image_api_key) || '',
    image_model: normalizeOptionalString(safePayload.image_model) || '',
    image_models: normalizeModels(safePayload.image_models, safePayload.image_model),
    image_last_refreshed_at: normalizeOptionalString(safePayload.image_last_refreshed_at),
  };
}

function normalizeModels(models, model) {
  const normalizedModels = [];
  const seen = new Set();
  const pushModel = (value) => {
    const normalized = normalizeOptionalString(value);
    if (!normalized || seen.has(normalized)) {
      return;
    }
    seen.add(normalized);
    normalizedModels.push(normalized);
  };

  pushModel(model);
  if (Array.isArray(models)) {
    for (const item of models) {
      pushModel(item);
    }
  }

  return normalizedModels;
}

function defaultBaseUrlForProvider(route) {
  const normalizedRoute = normalizeOptionalString(route)?.toLowerCase() || '';
  return LOCAL_PROXY_PROVIDER_ROUTES.has(normalizedRoute)
    ? DEFAULT_LOCAL_PROXY_BASE_URL
    : null;
}

function sanitizeProviderEntry(route, entry) {
  const safeEntry = entry && typeof entry === 'object' ? entry : {};
  const model = normalizeOptionalString(safeEntry.model) || normalizeModels(safeEntry.models, null)[0] || '';
  const baseUrl = normalizeOptionalString(safeEntry.base_url) || defaultBaseUrlForProvider(route) || '';
  return {
    route,
    name: normalizeOptionalString(safeEntry.name) || route,
    type: normalizeProviderType(safeEntry.type),
    enabled: typeof safeEntry.enabled === 'boolean' ? safeEntry.enabled : true,
    api_key: normalizeOptionalString(safeEntry.api_key) || '',
    base_url: baseUrl,
    model,
    models: normalizeModels(safeEntry.models, model),
    last_refreshed_at: normalizeOptionalString(safeEntry.last_refreshed_at),
  };
}

function sanitizeProviderConfig(payload) {
  const safePayload = payload && typeof payload === 'object' ? payload : {};
  const selectedProvider = normalizeOptionalString(safePayload.selected_provider);
  const providers = {};

  if (safePayload.providers && typeof safePayload.providers === 'object') {
    for (const [key, entry] of Object.entries(safePayload.providers)) {
      const normalizedKey = normalizeOptionalString(key);
      if (!normalizedKey) {
        continue;
      }
      providers[normalizedKey] = sanitizeProviderEntry(normalizedKey, entry);
    }
  }

  return {
    version: PROVIDER_CONFIG_VERSION,
    selected_provider: selectedProvider,
    providers,
  };
}

function sanitizeMigrationState(payload) {
  const safePayload = payload && typeof payload === 'object' ? payload : {};
  return {
    version: 1,
    completed:
      typeof safePayload.completed === 'boolean'
        ? safePayload.completed
        : DEFAULT_MIGRATION_STATE.completed,
    source_path: normalizeOptionalString(safePayload.source_path),
    imported_at: normalizeOptionalString(safePayload.imported_at),
  };
}

function loadSettings(runtimePaths) {
  return sanitizeSettings(readJsonFile(getSettingsFile(runtimePaths)));
}

function loadProviderConfig(runtimePaths) {
  return sanitizeProviderConfig(readJsonFile(getProvidersFile(runtimePaths)));
}

function saveSettings(runtimePaths, settings) {
  return writeJsonFile(getSettingsFile(runtimePaths), sanitizeSettings(settings));
}

function saveProviderConfig(runtimePaths, providerConfig) {
  return writeJsonFile(getProvidersFile(runtimePaths), sanitizeProviderConfig(providerConfig));
}

function loadMigrationState(runtimePaths) {
  return sanitizeMigrationState(readJsonFile(getMigrationStateFile(runtimePaths)));
}

function isCompleteProviderEntry(provider) {
  const route = normalizeOptionalString(provider?.route);
  const baseUrl = normalizeOptionalString(provider?.base_url) || defaultBaseUrlForProvider(route);
  return Boolean(
    provider?.enabled !== false
    && normalizeOptionalString(provider?.api_key)
    && baseUrl,
  );
}

function resolveActiveProviderConfig(providerConfig) {
  const sanitized = sanitizeProviderConfig(providerConfig);
  const providers = sanitized.providers || {};
  const selectedProvider = normalizeOptionalString(sanitized.selected_provider);
  const candidateRoutes = [];

  if (selectedProvider) {
    candidateRoutes.push(selectedProvider);
  }
  for (const route of Object.keys(providers)) {
    if (!candidateRoutes.includes(route)) {
      candidateRoutes.push(route);
    }
  }

  for (const route of candidateRoutes) {
    const provider = providers[route];
    if (!isCompleteProviderEntry(provider)) {
      continue;
    }
    return {
      route,
      name: normalizeOptionalString(provider.name) || route,
      type: normalizeProviderType(provider.type),
      api_key: normalizeOptionalString(provider.api_key),
      base_url: normalizeOptionalString(provider.base_url) || defaultBaseUrlForProvider(route),
      model: normalizeOptionalString(provider.model) || '',
      models: normalizeModels(provider.models, provider.model),
    };
  }

  return null;
}

function normalizeProviderSelection(providerConfig) {
  const sanitized = sanitizeProviderConfig(providerConfig);
  const activeProvider = resolveActiveProviderConfig(sanitized);
  if (!activeProvider) {
    return sanitized;
  }

  return {
    ...sanitized,
    selected_provider: activeProvider.route,
  };
}

function hasProviderConfig(providerConfig) {
  return Boolean(resolveActiveProviderConfig(providerConfig));
}

function maskApiKey(apiKey) {
  return normalizeOptionalString(apiKey) ? '********' : '';
}

function maskProviderConfig(providerConfig) {
  const sanitized = normalizeProviderSelection(providerConfig);
  const providers = {};
  for (const [route, provider] of Object.entries(sanitized.providers)) {
    providers[route] = {
      ...provider,
      api_key: maskApiKey(provider.api_key),
      has_api_key: Boolean(normalizeOptionalString(provider.api_key)),
    };
  }

  return {
    ...sanitized,
    providers,
  };
}

function buildRuntimePathEntries(runtimePaths) {
  return {
    config: runtimePaths.configDir,
    history: runtimePaths.historyDir,
    logs: runtimePaths.logDir,
    plots: runtimePaths.plotDir,
    cache: runtimePaths.cacheDir,
    runtime: runtimePaths.runtimeDir,
    data: runtimePaths.dataDir,
  };
}

function buildSettingsState({
  runtimePaths,
  projectRoot,
  appVersion = '0.0.0',
  appBuildInfo = {},
  appMode,
  systemLocale = 'en-US',
} = {}) {
  const settings = loadSettings(runtimePaths);
  const providerConfig = loadProviderConfig(runtimePaths);
  const migrationState = loadMigrationState(runtimePaths);
  const runtimePathEntries = buildRuntimePathEntries(runtimePaths);

  return {
    mode: 'electron',
    settings: {
      displayLanguage: settings.display_language,
      theme: settings.theme,
      themeMode: settings.theme_mode,
      launchAtLogin: settings.launch_at_login,
      backgroundMode: settings.background_mode,
      actionPlanAutoGenerate: settings.action_plan_auto_generate,
      voiceProviderMode: settings.voice_provider_mode,
      voiceBaseUrl: settings.voice_base_url,
      voiceApiKey: maskApiKey(settings.voice_api_key),
      voiceHasApiKey: Boolean(normalizeOptionalString(settings.voice_api_key)),
      voiceModel: settings.voice_model,
      voiceModels: settings.voice_models,
      voiceLastRefreshedAt: settings.voice_last_refreshed_at,
      imageProviderMode: settings.image_provider_mode,
      imageBaseUrl: settings.image_base_url,
      imageApiKey: maskApiKey(settings.image_api_key),
      imageHasApiKey: Boolean(normalizeOptionalString(settings.image_api_key)),
      imageModel: settings.image_model,
      imageModels: settings.image_models,
      imageLastRefreshedAt: settings.image_last_refreshed_at,
    },
    provider: maskProviderConfig(providerConfig),
    runtimePaths: runtimePathEntries,
    migration: {
      completed: migrationState.completed,
      sourcePath: migrationState.source_path || detectLegacyRoot({ runtimePaths, projectRoot }),
      importedAt: migrationState.imported_at,
    },
    app: {
      version: appVersion,
      buildDate: normalizeOptionalString(appBuildInfo.build_date),
      buildCommit: normalizeOptionalString(appBuildInfo.build_commit),
      mode: appMode || runtimePaths.appMode || 'development',
      backendRuntimePath: runtimePaths.runtimeDir,
      dataDir: runtimePaths.dataDir,
    },
    systemLocale,
  };
}

function buildProviderConfigFromSettingsPayload(payload, currentProviderConfig) {
  const currentConfig = normalizeProviderSelection(currentProviderConfig);
  if (payload && typeof payload.providerConfig === 'object') {
    const submittedConfig = sanitizeProviderConfig(payload.providerConfig);
    const submittedProviders = {};
    for (const [route, provider] of Object.entries(submittedConfig.providers)) {
      const currentProvider = currentConfig.providers?.[route] || {};
      const submittedApiKey = normalizeOptionalString(provider.api_key);
      const apiKey =
        submittedApiKey && submittedApiKey !== '********'
          ? submittedApiKey
          : (normalizeOptionalString(currentProvider.api_key) || '');
      submittedProviders[route] = {
        ...provider,
        api_key: apiKey,
      };
    }

    return normalizeProviderSelection({
      version: PROVIDER_CONFIG_VERSION,
      selected_provider: submittedConfig.selected_provider,
      providers: submittedProviders,
    });
  }

  const providerPayload = payload && typeof payload.provider === 'object' ? payload.provider : {};
  const currentProviders = currentConfig.providers || {};
  const submittedRoute = normalizeOptionalString(providerPayload.route);
  const submittedApiKey = normalizeOptionalString(providerPayload.apiKey);
  const submittedBaseUrl = normalizeOptionalString(providerPayload.baseUrl);
  const submittedModel = normalizeOptionalString(providerPayload.model);
  const providerHasRuntimeFields = Boolean(
    submittedApiKey || submittedBaseUrl || submittedModel,
  );

  if (!providerHasRuntimeFields) {
    if (submittedRoute && isCompleteProviderEntry(currentProviders[submittedRoute])) {
      return {
        ...currentConfig,
        selected_provider: submittedRoute,
      };
    }
    return currentConfig;
  }

  const selectedProvider =
    submittedRoute
    || normalizeOptionalString(currentConfig.selected_provider)
    || 'cliproxyapi';
  const currentProvider = currentProviders[selectedProvider] || {};
  const apiKey =
    submittedApiKey && submittedApiKey !== '********'
      ? submittedApiKey
      : (normalizeOptionalString(currentProvider.api_key) || '');

  return normalizeProviderSelection({
    version: PROVIDER_CONFIG_VERSION,
    selected_provider: selectedProvider,
    providers: {
      ...currentProviders,
      [selectedProvider]: {
        route: selectedProvider,
        name: normalizeOptionalString(currentProvider.name) || selectedProvider,
        type: normalizeProviderType(currentProvider.type),
        enabled: currentProvider.enabled !== false,
        api_key: apiKey,
        base_url:
          submittedBaseUrl
          || normalizeOptionalString(currentProvider.base_url)
          || '',
        model:
          submittedModel
          || normalizeOptionalString(currentProvider.model)
          || '',
        models: normalizeModels(currentProvider.models, submittedModel || currentProvider.model),
        last_refreshed_at: normalizeOptionalString(currentProvider.last_refreshed_at),
      },
    },
  });
}

function saveSettingsPayload({
  runtimePaths,
  payload,
  projectRoot,
  appVersion = '0.0.0',
  appBuildInfo = {},
  appMode,
  systemLocale = 'en-US',
} = {}) {
  const currentSettings = loadSettings(runtimePaths);
  const currentProviderConfig = loadProviderConfig(runtimePaths);
  const safePayload = payload && typeof payload === 'object' ? payload : {};

  saveSettings(runtimePaths, {
    ...currentSettings,
    display_language: sanitizeDisplayLanguage(safePayload.displayLanguage),
    theme: sanitizeTheme(
      Object.prototype.hasOwnProperty.call(safePayload, 'theme')
        ? safePayload.theme
        : currentSettings.theme,
    ),
    theme_mode: sanitizeThemeMode(
      Object.prototype.hasOwnProperty.call(safePayload, 'themeMode')
        ? safePayload.themeMode
        : currentSettings.theme_mode,
      Object.prototype.hasOwnProperty.call(safePayload, 'theme')
        ? safePayload.theme
        : currentSettings.theme,
    ),
    launch_at_login:
      typeof safePayload.launchAtLogin === 'boolean'
        ? safePayload.launchAtLogin
        : currentSettings.launch_at_login,
    background_mode: sanitizeBackgroundMode(safePayload.backgroundMode),
    action_plan_auto_generate:
      typeof safePayload.actionPlanAutoGenerate === 'boolean'
        ? safePayload.actionPlanAutoGenerate
        : currentSettings.action_plan_auto_generate,
    voice_provider_mode: Object.prototype.hasOwnProperty.call(safePayload, 'voiceProviderMode')
      ? (safePayload.voiceProviderMode === 'custom' ? 'custom' : 'inherit_ai')
      : currentSettings.voice_provider_mode,
    voice_base_url: Object.prototype.hasOwnProperty.call(safePayload, 'voiceBaseUrl')
      ? (normalizeOptionalString(safePayload.voiceBaseUrl) || '')
      : currentSettings.voice_base_url,
    voice_api_key: (() => {
      if (!Object.prototype.hasOwnProperty.call(safePayload, 'voiceApiKey')) {
        return currentSettings.voice_api_key;
      }
      const submitted = normalizeOptionalString(safePayload.voiceApiKey);
      if (!submitted || submitted === '********') {
        return submitted === '********' ? currentSettings.voice_api_key : '';
      }
      return submitted;
    })(),
    voice_model: Object.prototype.hasOwnProperty.call(safePayload, 'voiceModel')
      ? (normalizeOptionalString(safePayload.voiceModel) || DEFAULT_SETTINGS.voice_model)
      : currentSettings.voice_model,
    voice_models: Object.prototype.hasOwnProperty.call(safePayload, 'voiceModels')
      ? normalizeModels(safePayload.voiceModels, safePayload.voiceModel || currentSettings.voice_model)
      : currentSettings.voice_models,
    voice_last_refreshed_at: Object.prototype.hasOwnProperty.call(safePayload, 'voiceLastRefreshedAt')
      ? normalizeOptionalString(safePayload.voiceLastRefreshedAt)
      : currentSettings.voice_last_refreshed_at,
    image_provider_mode: Object.prototype.hasOwnProperty.call(safePayload, 'imageProviderMode')
      ? (safePayload.imageProviderMode === 'custom' ? 'custom' : 'inherit_ai')
      : currentSettings.image_provider_mode,
    image_base_url: Object.prototype.hasOwnProperty.call(safePayload, 'imageBaseUrl')
      ? (normalizeOptionalString(safePayload.imageBaseUrl) || '')
      : currentSettings.image_base_url,
    image_api_key: (() => {
      if (!Object.prototype.hasOwnProperty.call(safePayload, 'imageApiKey')) {
        return currentSettings.image_api_key;
      }
      const submitted = normalizeOptionalString(safePayload.imageApiKey);
      if (!submitted || submitted === '********') {
        return submitted === '********' ? currentSettings.image_api_key : '';
      }
      return submitted;
    })(),
    image_model: Object.prototype.hasOwnProperty.call(safePayload, 'imageModel')
      ? (normalizeOptionalString(safePayload.imageModel) || '')
      : currentSettings.image_model,
    image_models: Object.prototype.hasOwnProperty.call(safePayload, 'imageModels')
      ? normalizeModels(safePayload.imageModels, safePayload.imageModel || currentSettings.image_model)
      : currentSettings.image_models,
    image_last_refreshed_at: Object.prototype.hasOwnProperty.call(safePayload, 'imageLastRefreshedAt')
      ? normalizeOptionalString(safePayload.imageLastRefreshedAt)
      : currentSettings.image_last_refreshed_at,
  });

  saveProviderConfig(
    runtimePaths,
    buildProviderConfigFromSettingsPayload(safePayload, currentProviderConfig),
  );

  return buildSettingsState({
    runtimePaths,
    projectRoot,
    appVersion,
    appBuildInfo,
    appMode,
    systemLocale,
  });
}

function detectLegacyRoot({ runtimePaths, projectRoot }) {
  const normalizedProjectRoot = normalizeOptionalString(projectRoot);
  if (!normalizedProjectRoot) {
    return null;
  }

  const resolvedProjectRoot = path.resolve(normalizedProjectRoot);
  const resolvedDataDir = runtimePaths.dataDir ? path.resolve(runtimePaths.dataDir) : null;
  if (resolvedDataDir && resolvedProjectRoot === resolvedDataDir) {
    return null;
  }

  return fs.existsSync(path.join(resolvedProjectRoot, 'history')) ? resolvedProjectRoot : null;
}

function getOnboardingState({ runtimePaths, projectRoot }) {
  const settings = loadSettings(runtimePaths);
  const providerConfig = loadProviderConfig(runtimePaths);
  const migrationState = loadMigrationState(runtimePaths);

  return {
    completed: settings.onboarding_completed,
    launchAtLogin: settings.launch_at_login,
    displayLanguage: settings.display_language,
    providerConfigured: hasProviderConfig(providerConfig),
    migrationCompleted: migrationState.completed,
    legacyRoot: migrationState.source_path || detectLegacyRoot({ runtimePaths, projectRoot }),
  };
}

function copyDirectoryMissing(sourceDir, targetDir) {
  ensureDir(targetDir);
  for (const entry of fs.readdirSync(sourceDir, { withFileTypes: true })) {
    const sourcePath = path.join(sourceDir, entry.name);
    const targetPath = path.join(targetDir, entry.name);
    if (entry.isDirectory()) {
      copyDirectoryMissing(sourcePath, targetPath);
      continue;
    }
    if (!fs.existsSync(targetPath)) {
      ensureDir(path.dirname(targetPath));
      fs.copyFileSync(sourcePath, targetPath);
    }
  }
}

function buildProviderConfigFromSubmission(submission) {
  if (submission.skipChatSetup) {
    return { ...DEFAULT_PROVIDER_CONFIG };
  }

  const selectedProvider = normalizeOptionalString(submission.selectedProvider) || 'openai';
  return {
    version: PROVIDER_CONFIG_VERSION,
    selected_provider: selectedProvider,
    providers: {
      [selectedProvider]: {
        route: selectedProvider,
        name: selectedProvider,
        type: PROVIDER_TYPE_OPENAI_COMPATIBLE,
        enabled: true,
        api_key: normalizeOptionalString(submission.apiKey) || '',
        base_url: normalizeOptionalString(submission.baseUrl) || '',
        model: normalizeOptionalString(submission.model) || '',
        models: normalizeModels([], submission.model),
        last_refreshed_at: null,
      },
    },
  };
}

function migrateLegacyHistory({ runtimePaths, legacyRoot, importLegacyData, now }) {
  const existingState = loadMigrationState(runtimePaths);
  if (!importLegacyData) {
    return {
      imported: false,
      completed: existingState.completed,
      sourcePath: existingState.source_path,
    };
  }

  const normalizedLegacyRoot = normalizeOptionalString(legacyRoot);
  if (!normalizedLegacyRoot) {
    throw new Error('Legacy history import requires a source folder.');
  }

  const resolvedLegacyRoot = path.resolve(normalizedLegacyRoot);
  if (existingState.completed && existingState.source_path === resolvedLegacyRoot) {
    return {
      imported: false,
      completed: true,
      sourcePath: resolvedLegacyRoot,
    };
  }

  const sourceHistoryDir = path.join(resolvedLegacyRoot, 'history');
  if (!fs.existsSync(sourceHistoryDir)) {
    throw new Error('Legacy history folder was not found in the selected source.');
  }

  const targetHistoryDir = path.resolve(runtimePaths.historyDir);
  ensureDir(targetHistoryDir);
  const sameRoot = path.resolve(sourceHistoryDir) === targetHistoryDir;
  if (!sameRoot) {
    copyDirectoryMissing(sourceHistoryDir, targetHistoryDir);
  }

  const nextState = {
    version: 1,
    completed: true,
    source_path: resolvedLegacyRoot,
    imported_at: existingState.imported_at || now(),
  };
  writeJsonFile(getMigrationStateFile(runtimePaths), nextState);

  return {
    imported: !sameRoot,
    completed: true,
    sourcePath: resolvedLegacyRoot,
  };
}

function saveOnboardingCompletion({ runtimePaths, submission, projectRoot, now = () => new Date().toISOString() }) {
  const currentSettings = loadSettings(runtimePaths);
  const settings = {
    version: 1,
    onboarding_completed: true,
    launch_at_login: Boolean(submission.launchAtLogin),
    display_language: sanitizeDisplayLanguage(
      submission.displayLanguage ?? currentSettings.display_language,
    ),
    theme: currentSettings.theme,
    theme_mode: currentSettings.theme_mode,
    background_mode: currentSettings.background_mode,
    action_plan_auto_generate: currentSettings.action_plan_auto_generate,
    voice_base_url: currentSettings.voice_base_url,
    voice_api_key: currentSettings.voice_api_key,
    voice_model: currentSettings.voice_model,
    image_base_url: currentSettings.image_base_url,
    image_api_key: currentSettings.image_api_key,
    image_model: currentSettings.image_model,
  };
  writeJsonFile(getSettingsFile(runtimePaths), settings);

  const providerConfig = buildProviderConfigFromSubmission(submission);
  writeJsonFile(getProvidersFile(runtimePaths), providerConfig);

  const migration = migrateLegacyHistory({
    runtimePaths,
    legacyRoot: submission.legacyRoot || detectLegacyRoot({ runtimePaths, projectRoot }),
    importLegacyData: Boolean(submission.importLegacyData),
    now,
  });

  return {
    completed: true,
    launchAtLogin: settings.launch_at_login,
    providerConfigured: hasProviderConfig(providerConfig),
    migration,
  };
}

module.exports = {
  DEFAULT_SETTINGS,
  DEFAULT_PROVIDER_CONFIG,
  DEFAULT_MIGRATION_STATE,
  buildRuntimePathEntries,
  buildSettingsState,
  detectLegacyRoot,
  getMigrationStateFile,
  getOnboardingState,
  getProvidersFile,
  getSettingsFile,
  loadMigrationState,
  loadProviderConfig,
  loadSettings,
  maskProviderConfig,
  sanitizeBackgroundMode,
  sanitizeDisplayLanguage,
  sanitizeMigrationState,
  sanitizeProviderConfig,
  sanitizeSettings,
  sanitizeTheme,
  sanitizeThemeMode,
  saveProviderConfig,
  saveSettings,
  saveSettingsPayload,
  saveOnboardingCompletion,
  resolveActiveProviderConfig,
};

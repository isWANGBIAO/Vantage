const fs = require('fs');
const path = require('path');

const DEFAULT_SETTINGS = {
  version: 1,
  onboarding_completed: false,
  launch_at_login: false,
  display_language: 'system',
  theme: 'dark',
  background_mode: 'balanced',
};

const PROVIDER_CONFIG_VERSION = 2;
const PROVIDER_TYPE_OPENAI_COMPATIBLE = 'openai-compatible';

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

function sanitizeBackgroundMode(value) {
  return value === 'balanced' || value === 'prewarm' || value === 'power_saver'
    ? value
    : DEFAULT_SETTINGS.background_mode;
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
    background_mode: sanitizeBackgroundMode(safePayload.background_mode),
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

function sanitizeProviderEntry(route, entry) {
  const safeEntry = entry && typeof entry === 'object' ? entry : {};
  const model = normalizeOptionalString(safeEntry.model) || normalizeModels(safeEntry.models, null)[0] || '';
  return {
    route,
    name: normalizeOptionalString(safeEntry.name) || route,
    type: normalizeProviderType(safeEntry.type),
    enabled: typeof safeEntry.enabled === 'boolean' ? safeEntry.enabled : true,
    api_key: normalizeOptionalString(safeEntry.api_key) || '',
    base_url: normalizeOptionalString(safeEntry.base_url) || '',
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
  return Boolean(
    provider?.enabled !== false
    && normalizeOptionalString(provider?.api_key)
    && normalizeOptionalString(provider?.base_url)
    && normalizeOptionalString(provider?.model),
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
      base_url: normalizeOptionalString(provider.base_url),
      model: normalizeOptionalString(provider.model),
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
      launchAtLogin: settings.launch_at_login,
      backgroundMode: settings.background_mode,
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
  appMode,
  systemLocale = 'en-US',
} = {}) {
  const currentSettings = loadSettings(runtimePaths);
  const currentProviderConfig = loadProviderConfig(runtimePaths);
  const safePayload = payload && typeof payload === 'object' ? payload : {};

  saveSettings(runtimePaths, {
    ...currentSettings,
    display_language: sanitizeDisplayLanguage(safePayload.displayLanguage),
    theme: sanitizeTheme(safePayload.theme),
    launch_at_login:
      typeof safePayload.launchAtLogin === 'boolean'
        ? safePayload.launchAtLogin
        : currentSettings.launch_at_login,
    background_mode: sanitizeBackgroundMode(safePayload.backgroundMode),
  });

  saveProviderConfig(
    runtimePaths,
    buildProviderConfigFromSettingsPayload(safePayload, currentProviderConfig),
  );

  return buildSettingsState({
    runtimePaths,
    projectRoot,
    appVersion,
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
    background_mode: currentSettings.background_mode,
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
  saveProviderConfig,
  saveSettings,
  saveSettingsPayload,
  saveOnboardingCompletion,
  resolveActiveProviderConfig,
};

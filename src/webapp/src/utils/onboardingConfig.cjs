const fs = require('fs');
const path = require('path');

const DEFAULT_SETTINGS = {
  version: 1,
  onboarding_completed: false,
  launch_at_login: false,
};

const DEFAULT_PROVIDER_CONFIG = {
  version: 1,
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

function sanitizeProviderEntry(entry) {
  const safeEntry = entry && typeof entry === 'object' ? entry : {};
  return {
    api_key: normalizeOptionalString(safeEntry.api_key) || '',
    base_url: normalizeOptionalString(safeEntry.base_url) || '',
    model: normalizeOptionalString(safeEntry.model) || '',
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
      providers[normalizedKey] = sanitizeProviderEntry(entry);
    }
  }

  return {
    version: 1,
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

function loadMigrationState(runtimePaths) {
  return sanitizeMigrationState(readJsonFile(getMigrationStateFile(runtimePaths)));
}

function hasProviderConfig(providerConfig) {
  if (!providerConfig.selected_provider) {
    return false;
  }
  return Boolean(providerConfig.providers[providerConfig.selected_provider]);
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
    version: 1,
    selected_provider: selectedProvider,
    providers: {
      [selectedProvider]: {
        api_key: normalizeOptionalString(submission.apiKey) || '',
        base_url: normalizeOptionalString(submission.baseUrl) || '',
        model: normalizeOptionalString(submission.model) || '',
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
  const settings = {
    version: 1,
    onboarding_completed: true,
    launch_at_login: Boolean(submission.launchAtLogin),
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
  detectLegacyRoot,
  getMigrationStateFile,
  getOnboardingState,
  getProvidersFile,
  getSettingsFile,
  loadMigrationState,
  loadProviderConfig,
  loadSettings,
  sanitizeMigrationState,
  sanitizeProviderConfig,
  sanitizeSettings,
  saveOnboardingCompletion,
};

const fs = require('fs');
const os = require('os');
const path = require('path');

const APP_NAME = 'Vantage';
const DEV_APP_NAME = 'Vantage-dev';

function resolveAppMode({ appMode, env = {}, app } = {}) {
  if (appMode) {
    return appMode;
  }
  if (env.VANTAGE_APP_MODE) {
    return env.VANTAGE_APP_MODE;
  }
  if (app && app.isPackaged) {
    return 'packaged';
  }
  return 'development';
}

function resolveDefaultUserDataDir(appName, { env = {}, platform = process.platform } = {}) {
  if (env.LOCALAPPDATA) {
    return path.join(env.LOCALAPPDATA, appName);
  }

  if (platform === 'win32') {
    return path.join(env.USERPROFILE || os.homedir(), 'AppData', 'Local', appName);
  }

  return path.join(os.homedir(), '.local', 'share', appName);
}

function resolveDefaultPackagedDataDir({ env = {}, platform = process.platform } = {}) {
  return resolveDefaultUserDataDir(APP_NAME, { env, platform });
}

function resolveDefaultDevelopmentHistoryDir({ env = {}, platform = process.platform } = {}) {
  return path.join(resolveDefaultUserDataDir(DEV_APP_NAME, { env, platform }), 'history');
}

function resolveRuntimePaths({ appMode, env = {}, projectRoot, platform = process.platform, app } = {}) {
  const resolvedAppMode = resolveAppMode({ appMode, env, app });
  const dataDir = env.VANTAGE_DATA_DIR || (
    resolvedAppMode === 'packaged'
      ? resolveDefaultPackagedDataDir({ env, platform })
      : projectRoot
  );
  const historyDir = env.VANTAGE_HISTORY_DIR || (
    env.VANTAGE_DATA_DIR || resolvedAppMode === 'packaged'
      ? path.join(dataDir, 'history')
      : resolveDefaultDevelopmentHistoryDir({ env, platform })
  );

  return {
    appMode: resolvedAppMode,
    dataDir,
    configDir: env.VANTAGE_CONFIG_DIR || path.join(dataDir, 'config'),
    historyDir,
    logDir: env.VANTAGE_LOG_DIR || path.join(dataDir, 'logs'),
    plotDir: env.VANTAGE_PLOT_DIR || path.join(dataDir, 'plot_outputs'),
    cacheDir: env.VANTAGE_CACHE_DIR || path.join(dataDir, 'cache'),
    runtimeDir: env.VANTAGE_RUNTIME_DIR || path.join(dataDir, 'runtime'),
    migrationDir: env.VANTAGE_MIGRATION_DIR || path.join(dataDir, 'migration'),
  };
}

function ensureRuntimeDirs(runtimePaths, fsModule = fs) {
  for (const key of [
    'dataDir',
    'configDir',
    'historyDir',
    'logDir',
    'plotDir',
    'cacheDir',
    'runtimeDir',
    'migrationDir',
  ]) {
    fsModule.mkdirSync(runtimePaths[key], { recursive: true });
  }
}

module.exports = {
  APP_NAME,
  ensureRuntimeDirs,
  resolveAppMode,
  resolveRuntimePaths,
};

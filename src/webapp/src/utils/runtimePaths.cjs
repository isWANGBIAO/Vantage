const fs = require('fs');
const os = require('os');
const path = require('path');

const APP_NAME = 'Vantage';
const DEV_APP_NAME = 'Vantage-dev';

function pathForPlatform(platform = process.platform) {
  return platform === 'win32' ? path.win32 : path.posix;
}

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
  const pathModule = pathForPlatform(platform);
  if (env.LOCALAPPDATA) {
    return pathModule.join(env.LOCALAPPDATA, appName);
  }

  if (platform === 'win32') {
    return pathModule.join(env.USERPROFILE || os.homedir(), 'AppData', 'Local', appName);
  }

  if (platform === 'darwin') {
    return pathModule.join(env.HOME || os.homedir(), 'Library', 'Application Support', appName);
  }

  return pathModule.join(env.HOME || os.homedir(), '.local', 'share', appName);
}

function resolveDefaultPackagedDataDir({ env = {}, platform = process.platform } = {}) {
  return resolveDefaultUserDataDir(APP_NAME, { env, platform });
}

function resolveDefaultDevelopmentHistoryDir({ env = {}, platform = process.platform } = {}) {
  return pathForPlatform(platform).join(resolveDefaultUserDataDir(DEV_APP_NAME, { env, platform }), 'history');
}

function resolveRuntimePaths({ appMode, env = {}, projectRoot, platform = process.platform, app } = {}) {
  const resolvedAppMode = resolveAppMode({ appMode, env, app });
  const pathModule = pathForPlatform(platform);
  const dataDir = env.VANTAGE_DATA_DIR || (
    resolvedAppMode === 'packaged'
      ? resolveDefaultPackagedDataDir({ env, platform })
      : projectRoot
  );
  const historyDir = env.VANTAGE_HISTORY_DIR || (
    env.VANTAGE_DATA_DIR || resolvedAppMode === 'packaged'
      ? pathModule.join(dataDir, 'history')
      : resolveDefaultDevelopmentHistoryDir({ env, platform })
  );

  return {
    appMode: resolvedAppMode,
    dataDir,
    configDir: env.VANTAGE_CONFIG_DIR || pathModule.join(dataDir, 'config'),
    historyDir,
    logDir: env.VANTAGE_LOG_DIR || pathModule.join(dataDir, 'logs'),
    plotDir: env.VANTAGE_PLOT_DIR || pathModule.join(dataDir, 'plot_outputs'),
    cacheDir: env.VANTAGE_CACHE_DIR || pathModule.join(dataDir, 'cache'),
    runtimeDir: env.VANTAGE_RUNTIME_DIR || pathModule.join(dataDir, 'runtime'),
    migrationDir: env.VANTAGE_MIGRATION_DIR || pathModule.join(dataDir, 'migration'),
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

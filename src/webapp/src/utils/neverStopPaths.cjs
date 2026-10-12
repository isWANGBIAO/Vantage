const path = require('node:path');

function resolveNeverStopPaths({ runtimePaths, appDataDir, userDataDir, env = {} }) {
  const baseDir = runtimePaths.appMode === 'development' && !env.VANTAGE_DATA_DIR
    ? userDataDir
    : runtimePaths.dataDir;
  return {
    dataDir: path.join(baseDir, 'never-stop'),
    legacyDir: env.NEVER_STOP_DATA_DIR || path.join(appDataDir, 'VantageNeverStop'),
  };
}

module.exports = { resolveNeverStopPaths };

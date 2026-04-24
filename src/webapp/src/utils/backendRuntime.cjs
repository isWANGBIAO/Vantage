const fs = require('fs');
const http = require('http');
const path = require('path');
const { spawn, spawnSync } = require('child_process');
const { loadProviderConfig } = require('./onboardingConfig.cjs');

function resolveBundledBackendExecutable({
  env = process.env,
  resourcesPath = process.resourcesPath,
  platform = process.platform,
} = {}) {
  if (env.VANTAGE_BACKEND_EXECUTABLE) {
    return env.VANTAGE_BACKEND_EXECUTABLE;
  }

  const executableName = platform === 'win32' ? 'VantageBackend.exe' : 'VantageBackend';
  return path.join(resourcesPath, 'backend-runtime', 'VantageBackend', executableName);
}

function applySelectedProviderEnvironment(nextEnv, providerConfig) {
  const selectedProviderKey = providerConfig?.selected_provider;
  if (!selectedProviderKey) {
    return nextEnv;
  }

  const selectedProvider = providerConfig?.providers?.[selectedProviderKey];
  if (!selectedProvider || typeof selectedProvider !== 'object') {
    return nextEnv;
  }

  const apiKey = typeof selectedProvider.api_key === 'string' ? selectedProvider.api_key.trim() : '';
  const baseUrl = typeof selectedProvider.base_url === 'string' ? selectedProvider.base_url.trim() : '';
  const model = typeof selectedProvider.model === 'string' ? selectedProvider.model.trim() : '';

  if (apiKey) {
    nextEnv.CLIPROXYAPI_API_KEY = apiKey;
  }
  if (baseUrl) {
    nextEnv.CLIPROXYAPI_BASE_URL = baseUrl;
  }
  if (model) {
    nextEnv.CLIPROXYAPI_MODEL = model;
  }

  return nextEnv;
}

function buildBundledBackendEnvironment({
  runtimePaths,
  env = process.env,
  loadProviderConfigFn = loadProviderConfig,
} = {}) {
  const nextEnv = {
    ...env,
    VANTAGE_APP_MODE: 'packaged',
    VANTAGE_DATA_DIR: runtimePaths.dataDir,
    VANTAGE_CONFIG_DIR: runtimePaths.configDir,
    VANTAGE_HISTORY_DIR: runtimePaths.historyDir,
    VANTAGE_LOG_DIR: runtimePaths.logDir,
    VANTAGE_PLOT_DIR: runtimePaths.plotDir,
    VANTAGE_CACHE_DIR: runtimePaths.cacheDir,
    VANTAGE_RUNTIME_DIR: runtimePaths.runtimeDir,
    VANTAGE_MIGRATION_DIR: runtimePaths.migrationDir,
  };
  delete nextEnv.VANTAGE_PROJECT_ROOT;

  return applySelectedProviderEnvironment(nextEnv, loadProviderConfigFn(runtimePaths));
}

function requestBackendStatus({
  url = 'http://127.0.0.1:8000/api/status',
  timeoutMs = 5000,
} = {}) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { timeout: timeoutMs }, (response) => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => {
        body += chunk;
      });
      response.on('end', () => {
        if (response.statusCode < 200 || response.statusCode >= 300) {
          reject(new Error(`Backend status request failed: ${response.statusCode}`));
          return;
        }

        try {
          resolve(JSON.parse(body));
        } catch (error) {
          reject(error);
        }
      });
    });

    request.on('timeout', () => {
      request.destroy(new Error('Backend status request timed out'));
    });
    request.on('error', reject);
  });
}

async function waitForBackendStatus({
  timeoutMs = 60000,
  intervalMs = 1000,
  requestStatus = requestBackendStatus,
} = {}) {
  const deadline = Date.now() + timeoutMs;
  let lastError = new Error('Backend status is unavailable');

  while (Date.now() < deadline) {
    try {
      return await requestStatus();
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
  }

  throw lastError;
}

function terminateBundledBackendProcess(
  childProcess,
  {
    platform = process.platform,
    logger = console,
    killTree,
  } = {},
) {
  if (!childProcess || !childProcess.pid || childProcess.exitCode !== null) {
    return;
  }

  const resolvedKillTree = killTree || ((pid) => {
    if (platform === 'win32') {
      spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' });
      return;
    }
    try {
      process.kill(pid, 'SIGTERM');
    } catch (error) {
      if (error && error.code !== 'ESRCH') {
        throw error;
      }
    }
  });

  try {
    resolvedKillTree(childProcess.pid);
  } catch (error) {
    if (logger && typeof logger.warn === 'function') {
      logger.warn(`Failed to terminate bundled backend process ${childProcess.pid}: ${error.message}`);
    }
  }
}

async function ensureBundledBackendReady({
  isDev,
  runtimePaths,
  env = process.env,
  resourcesPath = process.resourcesPath,
  platform = process.platform,
  executablePath,
  fileExists = fs.existsSync,
  spawnProcess = spawn,
  waitForStatusFn = waitForBackendStatus,
  logger = console,
} = {}) {
  if (isDev) {
    return {
      started: false,
      reason: 'development',
      process: null,
      status: null,
    };
  }

  const resolvedExecutablePath = executablePath || resolveBundledBackendExecutable({
    env,
    resourcesPath,
    platform,
  });

  try {
    const status = await waitForStatusFn({ timeoutMs: 1000 });
    return {
      started: false,
      reason: 'already-running',
      process: null,
      status,
    };
  } catch (_error) {
  }

  if (!fileExists(resolvedExecutablePath)) {
    throw new Error(`Bundled backend executable not found: ${resolvedExecutablePath}`);
  }

  const childProcess = spawnProcess(resolvedExecutablePath, [], {
    cwd: path.dirname(resolvedExecutablePath),
    env: buildBundledBackendEnvironment({ runtimePaths, env }),
    stdio: 'ignore',
    windowsHide: true,
  });

  if (typeof childProcess.unref === 'function') {
    childProcess.unref();
  }

  try {
    const status = await waitForStatusFn({ timeoutMs: 60000 });
    return {
      started: true,
      reason: 'launched',
      process: childProcess,
      status,
      executablePath: resolvedExecutablePath,
    };
  } catch (error) {
    terminateBundledBackendProcess(childProcess, { platform, logger });
    throw new Error(`Failed to start bundled backend: ${error.message}`);
  }
}

module.exports = {
  buildBundledBackendEnvironment,
  ensureBundledBackendReady,
  requestBackendStatus,
  resolveBundledBackendExecutable,
  terminateBundledBackendProcess,
  waitForBackendStatus,
};

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const {
  resolveBundledBackendExecutable,
  buildBundledBackendEnvironment,
  ensureBundledBackendReady,
} = require('./backendRuntime.cjs');

const runtimePaths = {
  appMode: 'packaged',
  dataDir: 'C:\\Users\\97012\\AppData\\Local\\Vantage',
  configDir: 'C:\\Users\\97012\\AppData\\Local\\Vantage\\config',
  historyDir: 'C:\\Users\\97012\\AppData\\Local\\Vantage\\history',
  logDir: 'C:\\Users\\97012\\AppData\\Local\\Vantage\\logs',
  plotDir: 'C:\\Users\\97012\\AppData\\Local\\Vantage\\plot_outputs',
  cacheDir: 'C:\\Users\\97012\\AppData\\Local\\Vantage\\cache',
  runtimeDir: 'C:\\Users\\97012\\AppData\\Local\\Vantage\\runtime',
  migrationDir: 'C:\\Users\\97012\\AppData\\Local\\Vantage\\migration',
};

test('resolveBundledBackendExecutable prefers an explicit override', () => {
  const executablePath = resolveBundledBackendExecutable({
    env: {
      VANTAGE_BACKEND_EXECUTABLE: 'D:\\runtime\\VantageBackend.exe',
    },
    resourcesPath: 'C:\\resources',
    platform: 'win32',
  });

  assert.equal(executablePath, 'D:\\runtime\\VantageBackend.exe');
});

test('buildBundledBackendEnvironment injects the packaged runtime contract', () => {
  const env = buildBundledBackendEnvironment({
    runtimePaths,
    env: {
      PATH: 'C:\\Windows\\System32',
      VANTAGE_PROJECT_ROOT: 'C:\\repo\\ai',
    },
  });

  assert.equal(env.PATH, 'C:\\Windows\\System32');
  assert.equal(env.VANTAGE_APP_MODE, 'packaged');
  assert.equal(env.VANTAGE_DATA_DIR, runtimePaths.dataDir);
  assert.equal(env.VANTAGE_CONFIG_DIR, runtimePaths.configDir);
  assert.equal(env.VANTAGE_HISTORY_DIR, runtimePaths.historyDir);
  assert.equal(env.VANTAGE_LOG_DIR, runtimePaths.logDir);
  assert.equal(env.VANTAGE_PLOT_DIR, runtimePaths.plotDir);
  assert.equal(env.VANTAGE_CACHE_DIR, runtimePaths.cacheDir);
  assert.equal(env.VANTAGE_RUNTIME_DIR, runtimePaths.runtimeDir);
  assert.equal(env.VANTAGE_MIGRATION_DIR, runtimePaths.migrationDir);
  assert.equal('VANTAGE_PROJECT_ROOT' in env, false);
});

test('buildBundledBackendEnvironment maps selected onboarding provider into backend env', () => {
  const env = buildBundledBackendEnvironment({
    runtimePaths,
    env: {
      PATH: 'C:\\Windows\\System32',
    },
    loadProviderConfigFn: () => ({
      version: 1,
      selected_provider: 'custom',
      providers: {
        custom: {
          api_key: 'test-api-key',
          base_url: 'https://proxy.example.com/v1',
          model: 'gpt-5.4',
        },
      },
    }),
  });

  assert.equal(env.CLIPROXYAPI_API_KEY, 'test-api-key');
  assert.equal(env.CLIPROXYAPI_BASE_URL, 'https://proxy.example.com/v1');
  assert.equal(env.CLIPROXYAPI_MODEL, 'gpt-5.4');
});

test('buildBundledBackendEnvironment maps local proxy provider without a configured model', () => {
  const env = buildBundledBackendEnvironment({
    runtimePaths,
    env: {
      PATH: 'C:\\Windows\\System32',
    },
    loadProviderConfigFn: () => ({
      version: 2,
      selected_provider: 'custom',
      providers: {
        custom: {
          api_key: 'test-api-key',
          base_url: '',
          model: '',
        },
      },
    }),
  });

  assert.equal(env.CLIPROXYAPI_API_KEY, 'test-api-key');
  assert.equal(env.CLIPROXYAPI_BASE_URL, 'http://127.0.0.1:8317/v1');
  assert.equal('CLIPROXYAPI_MODEL' in env, false);
});

test('buildBundledBackendEnvironment maps a complete provider when selected provider is empty', () => {
  const env = buildBundledBackendEnvironment({
    runtimePaths,
    env: {
      PATH: 'C:\\Windows\\System32',
    },
    loadProviderConfigFn: () => ({
      version: 1,
      selected_provider: 'cliproxyapi',
      providers: {
        cliproxyapi: {
          api_key: '',
          base_url: '',
          model: '',
        },
        custom: {
          api_key: 'test-api-key',
          base_url: 'http://127.0.0.1:8317/v1',
          model: 'gpt-5.2',
        },
      },
    }),
  });

  assert.equal(env.CLIPROXYAPI_API_KEY, 'test-api-key');
  assert.equal(env.CLIPROXYAPI_BASE_URL, 'http://127.0.0.1:8317/v1');
  assert.equal(env.CLIPROXYAPI_MODEL, 'gpt-5.2');
});

test('ensureBundledBackendReady spawns the bundled backend in packaged mode', async () => {
  let spawnCall = null;
  const fakeChild = {
    pid: 4321,
    exitCode: null,
    unrefCalled: false,
    unref() {
      this.unrefCalled = true;
    },
  };

  let waitAttempts = 0;
  const result = await ensureBundledBackendReady({
    isDev: false,
    runtimePaths,
    executablePath: 'C:\\Program Files\\Vantage\\backend-runtime\\VantageBackend\\VantageBackend.exe',
    fileExists: () => true,
    spawnProcess: (file, args, options) => {
      spawnCall = { file, args, options };
      return fakeChild;
    },
    waitForStatusFn: async () => {
      waitAttempts += 1;
      if (waitAttempts === 1) {
        throw new Error('backend not ready yet');
      }
      return { camera_online: false };
    },
  });

  assert.equal(spawnCall.file, 'C:\\Program Files\\Vantage\\backend-runtime\\VantageBackend\\VantageBackend.exe');
  assert.deepEqual(spawnCall.args, []);
  assert.equal(
    spawnCall.options.cwd,
    path.win32.dirname('C:\\Program Files\\Vantage\\backend-runtime\\VantageBackend\\VantageBackend.exe'),
  );
  assert.equal(spawnCall.options.windowsHide, true);
  assert.equal(spawnCall.options.env.VANTAGE_APP_MODE, 'packaged');
  assert.equal(fakeChild.unrefCalled, true);
  assert.equal(result.started, true);
  assert.equal(result.status.camera_online, false);
});

test('ensureBundledBackendReady leaves development mode to the existing launcher flow', async () => {
  let spawned = false;

  const result = await ensureBundledBackendReady({
    isDev: true,
    runtimePaths,
    spawnProcess: () => {
      spawned = true;
      throw new Error('should not spawn in development mode');
    },
  });

  assert.equal(spawned, false);
  assert.equal(result.started, false);
  assert.equal(result.reason, 'development');
});

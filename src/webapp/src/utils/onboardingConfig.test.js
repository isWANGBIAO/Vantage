import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const {
  buildSettingsState,
  getOnboardingState,
  maskProviderConfig,
  saveSettingsPayload,
  saveOnboardingCompletion,
} = require('./onboardingConfig.cjs');

test('getOnboardingState defaults to incomplete when settings file is missing', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'vantage-onboarding-'));
  const runtimePaths = {
    configDir: path.join(root, 'config'),
    migrationDir: path.join(root, 'migration'),
    dataDir: path.join(root, 'data'),
  };

  const state = getOnboardingState({ runtimePaths });

  assert.deepEqual(state, {
    completed: false,
    launchAtLogin: false,
    displayLanguage: 'system',
    providerConfigured: false,
    migrationCompleted: false,
    legacyRoot: null,
  });
});

test('loadSettings defaults formal theme and background mode settings', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'vantage-settings-'));
  const runtimePaths = {
    configDir: path.join(root, 'config'),
    migrationDir: path.join(root, 'migration'),
    dataDir: path.join(root, 'data'),
  };

  const state = buildSettingsState({
    runtimePaths,
    projectRoot: root,
    appVersion: '1.2.3',
    appMode: 'packaged',
    systemLocale: 'zh-CN',
  });

  assert.equal(state.settings.theme, 'dark');
  assert.equal(state.settings.backgroundMode, 'balanced');
  assert.equal(state.app.version, '1.2.3');
  assert.equal(state.app.mode, 'packaged');
  assert.equal(state.systemLocale, 'zh-CN');
});

test('saveSettingsPayload persists general settings and provider config', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'vantage-settings-save-'));
  const runtimePaths = {
    configDir: path.join(root, 'config'),
    historyDir: path.join(root, 'history'),
    logDir: path.join(root, 'logs'),
    plotDir: path.join(root, 'plots'),
    cacheDir: path.join(root, 'cache'),
    runtimeDir: path.join(root, 'runtime'),
    migrationDir: path.join(root, 'migration'),
    dataDir: path.join(root, 'data'),
  };

  const state = saveSettingsPayload({
    runtimePaths,
    payload: {
      displayLanguage: 'en-US',
      theme: 'light',
      launchAtLogin: true,
      backgroundMode: 'power_saver',
      provider: {
        route: 'cliproxyapi',
        baseUrl: 'https://example.invalid/v1',
        apiKey: 'sk-demo-secret',
        model: 'gpt-5.4',
      },
    },
    appVersion: '1.2.3',
    appMode: 'packaged',
    systemLocale: 'en-US',
  });

  const settings = JSON.parse(
    readFileSync(path.join(runtimePaths.configDir, 'settings.json'), 'utf8'),
  );
  const providers = JSON.parse(
    readFileSync(path.join(runtimePaths.configDir, 'providers.json'), 'utf8'),
  );

  assert.equal(state.settings.displayLanguage, 'en-US');
  assert.equal(state.settings.theme, 'light');
  assert.equal(state.settings.launchAtLogin, true);
  assert.equal(state.settings.backgroundMode, 'power_saver');
  assert.equal(state.provider.providers.cliproxyapi.api_key, '********');
  assert.deepEqual(settings, {
    version: 1,
    onboarding_completed: false,
    launch_at_login: true,
    display_language: 'en-US',
    theme: 'light',
    background_mode: 'power_saver',
  });
  assert.deepEqual(providers, {
    version: 1,
    selected_provider: 'cliproxyapi',
    providers: {
      cliproxyapi: {
        api_key: 'sk-demo-secret',
        base_url: 'https://example.invalid/v1',
        model: 'gpt-5.4',
      },
    },
  });
});

test('maskProviderConfig hides saved API keys in settings state', () => {
  const masked = maskProviderConfig({
    version: 1,
    selected_provider: 'openai',
    providers: {
      openai: {
        api_key: 'sk-live-secret',
        base_url: 'https://example.invalid/v1',
        model: 'gpt-5',
      },
    },
  });

  assert.equal(masked.providers.openai.api_key, '********');
  assert.equal(masked.providers.openai.has_api_key, true);
});

test('getOnboardingState reads onboarding flags from settings.json', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'vantage-onboarding-'));
  const configDir = path.join(root, 'config');
  const migrationDir = path.join(root, 'migration');
  mkdirSync(configDir, { recursive: true });
  mkdirSync(migrationDir, { recursive: true });
  writeFileSync(
    path.join(configDir, 'settings.json'),
    JSON.stringify({
      version: 1,
      onboarding_completed: true,
      launch_at_login: true,
      display_language: 'zh-CN',
    }),
    'utf8',
  );
  writeFileSync(
    path.join(configDir, 'providers.json'),
    JSON.stringify({
      version: 1,
      selected_provider: 'openai',
      providers: {
        openai: {
          api_key: 'sk-demo',
        },
      },
    }),
    'utf8',
  );
  writeFileSync(
    path.join(migrationDir, 'migration-state.json'),
    JSON.stringify({
      version: 1,
      completed: true,
      source_path: 'C:\\legacy-root',
      imported_at: '2026-04-23T18:00:00.000Z',
    }),
    'utf8',
  );

  const state = getOnboardingState({
    runtimePaths: {
      configDir,
      migrationDir,
      dataDir: path.join(root, 'data'),
    },
  });

  assert.deepEqual(state, {
    completed: true,
    launchAtLogin: true,
    displayLanguage: 'zh-CN',
    providerConfigured: true,
    migrationCompleted: true,
    legacyRoot: 'C:\\legacy-root',
  });
});

test('saveOnboardingCompletion persists settings and provider config', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'vantage-onboarding-'));
  const runtimePaths = {
    configDir: path.join(root, 'config'),
    historyDir: path.join(root, 'history'),
    migrationDir: path.join(root, 'migration'),
    dataDir: path.join(root, 'data'),
  };

  const result = saveOnboardingCompletion({
    runtimePaths,
    submission: {
      launchAtLogin: true,
      selectedProvider: 'openai',
      apiKey: 'sk-demo',
      baseUrl: 'https://example.invalid/v1',
      model: 'gpt-5',
      displayLanguage: 'en-US',
      skipChatSetup: false,
      importLegacyData: false,
      legacyRoot: null,
    },
    now: () => '2026-04-23T18:00:00.000Z',
  });

  const settings = JSON.parse(
    readFileSync(path.join(runtimePaths.configDir, 'settings.json'), 'utf8'),
  );
  const providers = JSON.parse(
    readFileSync(path.join(runtimePaths.configDir, 'providers.json'), 'utf8'),
  );

  assert.equal(result.completed, true);
  assert.deepEqual(settings, {
    version: 1,
    onboarding_completed: true,
    launch_at_login: true,
    display_language: 'en-US',
    theme: 'dark',
    background_mode: 'balanced',
  });
  assert.deepEqual(providers, {
    version: 1,
    selected_provider: 'openai',
    providers: {
      openai: {
        api_key: 'sk-demo',
        base_url: 'https://example.invalid/v1',
        model: 'gpt-5',
      },
    },
  });
});

test('saveOnboardingCompletion imports legacy history once and records migration state', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'vantage-onboarding-'));
  const legacyRoot = path.join(root, 'legacy-root');
  const legacyHistoryDir = path.join(legacyRoot, 'history');
  const runtimePaths = {
    configDir: path.join(root, 'config'),
    historyDir: path.join(root, 'data', 'history'),
    migrationDir: path.join(root, 'data', 'migration'),
    dataDir: path.join(root, 'data'),
  };

  mkdirSync(path.join(legacyHistoryDir, 'sessions'), { recursive: true });
  writeFileSync(path.join(legacyHistoryDir, 'latest_context.json'), '{"ok":true}', 'utf8');
  writeFileSync(path.join(legacyHistoryDir, 'sessions', 'chat.json'), '{"messages":[]}', 'utf8');
  writeFileSync(path.join(legacyHistoryDir, 'state.db'), 'db', 'utf8');

  const first = saveOnboardingCompletion({
    runtimePaths,
    submission: {
      launchAtLogin: false,
      selectedProvider: 'openai',
      apiKey: '',
      baseUrl: '',
      model: '',
      displayLanguage: 'zh-CN',
      skipChatSetup: true,
      importLegacyData: true,
      legacyRoot,
    },
    now: () => '2026-04-23T18:00:00.000Z',
  });

  const second = saveOnboardingCompletion({
    runtimePaths,
    submission: {
      launchAtLogin: false,
      selectedProvider: 'openai',
      apiKey: '',
      baseUrl: '',
      model: '',
      displayLanguage: 'zh-CN',
      skipChatSetup: true,
      importLegacyData: true,
      legacyRoot,
    },
    now: () => '2026-04-23T18:05:00.000Z',
  });

  const migrationState = JSON.parse(
    readFileSync(path.join(runtimePaths.migrationDir, 'migration-state.json'), 'utf8'),
  );
  const settings = JSON.parse(
    readFileSync(path.join(runtimePaths.configDir, 'settings.json'), 'utf8'),
  );

  assert.equal(first.migration.imported, true);
  assert.equal(second.migration.imported, false);
  assert.equal(
    readFileSync(path.join(runtimePaths.historyDir, 'latest_context.json'), 'utf8'),
    '{"ok":true}',
  );
  assert.equal(
    readFileSync(path.join(runtimePaths.historyDir, 'sessions', 'chat.json'), 'utf8'),
    '{"messages":[]}',
  );
  assert.deepEqual(migrationState, {
    version: 1,
    completed: true,
    source_path: legacyRoot,
    imported_at: '2026-04-23T18:00:00.000Z',
  });
  assert.equal(settings.display_language, 'zh-CN');
});

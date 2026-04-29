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
  assert.equal(state.settings.themeMode, 'dark');
  assert.equal(state.settings.backgroundMode, 'balanced');
  assert.equal(state.settings.actionPlanAutoGenerate, true);
  assert.equal(state.settings.voiceBaseUrl, '');
  assert.equal(state.settings.voiceApiKey, '');
  assert.equal(state.settings.voiceModel, 'FunAudioLLM/SenseVoiceSmall');
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
      themeMode: 'auto',
      launchAtLogin: true,
      backgroundMode: 'power_saver',
      actionPlanAutoGenerate: false,
      voiceBaseUrl: 'https://voice.example.invalid/v1',
      voiceApiKey: 'sk-voice-secret',
      voiceModel: 'sensevoice',
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
  assert.equal(state.settings.themeMode, 'auto');
  assert.equal(state.settings.launchAtLogin, true);
  assert.equal(state.settings.backgroundMode, 'power_saver');
  assert.equal(state.settings.actionPlanAutoGenerate, false);
  assert.equal(state.settings.voiceBaseUrl, 'https://voice.example.invalid/v1');
  assert.equal(state.settings.voiceApiKey, '********');
  assert.equal(state.settings.voiceHasApiKey, true);
  assert.equal(state.settings.voiceModel, 'sensevoice');
  assert.equal(state.provider.providers.cliproxyapi.api_key, '********');
  assert.deepEqual(settings, {
    version: 1,
    onboarding_completed: false,
    launch_at_login: true,
    display_language: 'en-US',
    theme: 'light',
    theme_mode: 'auto',
    background_mode: 'power_saver',
    action_plan_auto_generate: false,
    voice_base_url: 'https://voice.example.invalid/v1',
    voice_api_key: 'sk-voice-secret',
    voice_model: 'sensevoice',
  });
  assert.deepEqual(providers, {
    version: 2,
    selected_provider: 'cliproxyapi',
    providers: {
      cliproxyapi: {
        route: 'cliproxyapi',
        name: 'cliproxyapi',
        type: 'openai-compatible',
        enabled: true,
        api_key: 'sk-demo-secret',
        base_url: 'https://example.invalid/v1',
        model: 'gpt-5.4',
        models: ['gpt-5.4'],
        last_refreshed_at: null,
      },
    },
  });
});

test('saveSettingsPayload persists multi provider settings without losing masked keys', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'vantage-settings-multi-provider-'));
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
  mkdirSync(runtimePaths.configDir, { recursive: true });
  writeFileSync(
    path.join(runtimePaths.configDir, 'providers.json'),
    JSON.stringify({
      version: 2,
      selected_provider: 'local',
      providers: {
        local: {
          route: 'local',
          name: 'Local Proxy',
          type: 'openai-compatible',
          enabled: true,
          api_key: 'sk-local-real',
          base_url: 'http://127.0.0.1:8317/v1',
          model: 'gpt-5.5',
          models: ['gpt-5.5'],
          last_refreshed_at: '2026-04-25T00:00:00.000Z',
        },
      },
    }),
    'utf8',
  );

  saveSettingsPayload({
    runtimePaths,
    payload: {
      displayLanguage: 'zh-CN',
      theme: 'dark',
      launchAtLogin: false,
      backgroundMode: 'balanced',
      providerConfig: {
        version: 2,
        selected_provider: 'cloud',
        providers: {
          local: {
            route: 'local',
            name: 'Local Proxy',
            type: 'openai-compatible',
            enabled: true,
            api_key: '********',
            base_url: 'http://127.0.0.1:8317/v1',
            model: 'gpt-5.5',
            models: ['gpt-5.5'],
            last_refreshed_at: '2026-04-25T00:00:00.000Z',
          },
          cloud: {
            route: 'cloud',
            name: 'Cloud Proxy',
            type: 'openai-compatible',
            enabled: false,
            api_key: 'sk-cloud',
            base_url: 'https://cloud.invalid/v1',
            model: 'gpt-5.4',
            models: ['gpt-5.4', 'gpt-5.3'],
            last_refreshed_at: null,
          },
        },
      },
    },
  });

  const providers = JSON.parse(
    readFileSync(path.join(runtimePaths.configDir, 'providers.json'), 'utf8'),
  );

  assert.equal(providers.version, 2);
  assert.equal(providers.providers.local.api_key, 'sk-local-real');
  assert.equal(providers.providers.cloud.enabled, false);
  assert.deepEqual(providers.providers.cloud.models, ['gpt-5.4', 'gpt-5.3']);
  assert.equal(providers.selected_provider, 'local');
});

test('buildSettingsState reports a complete provider when selected provider is empty', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'vantage-settings-provider-heal-'));
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
  mkdirSync(runtimePaths.configDir, { recursive: true });
  writeFileSync(
    path.join(runtimePaths.configDir, 'providers.json'),
    JSON.stringify({
      version: 1,
      selected_provider: 'cliproxyapi',
      providers: {
        cliproxyapi: {
          api_key: '',
          base_url: '',
          model: '',
        },
        custom: {
          api_key: 'sk-real',
          base_url: 'http://127.0.0.1:8317/v1',
          model: 'gpt-5.2',
        },
      },
    }),
    'utf8',
  );

  const state = buildSettingsState({
    runtimePaths,
    projectRoot: root,
  });

  assert.equal(state.provider.selected_provider, 'custom');
  assert.equal(state.provider.providers.custom.api_key, '********');
  assert.equal(state.provider.providers.custom.has_api_key, true);
});

test('buildSettingsState shows local proxy defaults for saved provider key', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'vantage-settings-local-proxy-default-'));
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
  mkdirSync(runtimePaths.configDir, { recursive: true });
  writeFileSync(
    path.join(runtimePaths.configDir, 'providers.json'),
    JSON.stringify({
      version: 2,
      selected_provider: 'custom',
      providers: {
        custom: {
          api_key: 'local-proxy-key',
          base_url: '',
          model: 'gpt-5.5',
        },
      },
    }),
    'utf8',
  );

  const state = buildSettingsState({
    runtimePaths,
    projectRoot: root,
  });

  assert.equal(state.provider.selected_provider, 'custom');
  assert.equal(state.provider.providers.custom.api_key, '********');
  assert.equal(state.provider.providers.custom.has_api_key, true);
  assert.equal(state.provider.providers.custom.base_url, 'http://127.0.0.1:8317/v1');
  assert.equal(state.provider.providers.custom.model, 'gpt-5.5');
});

test('saveSettingsPayload does not switch to an empty submitted provider', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'vantage-settings-save-provider-heal-'));
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
  mkdirSync(runtimePaths.configDir, { recursive: true });
  writeFileSync(
    path.join(runtimePaths.configDir, 'providers.json'),
    JSON.stringify({
      version: 1,
      selected_provider: 'custom',
      providers: {
        custom: {
          api_key: 'sk-real',
          base_url: 'http://127.0.0.1:8317/v1',
          model: 'gpt-5.2',
        },
      },
    }),
    'utf8',
  );

  saveSettingsPayload({
    runtimePaths,
    payload: {
      displayLanguage: 'zh-CN',
      theme: 'light',
      launchAtLogin: false,
      backgroundMode: 'balanced',
      provider: {
        route: 'cliproxyapi',
        apiKey: '',
        baseUrl: '',
        model: '',
      },
    },
  });

  const providers = JSON.parse(
    readFileSync(path.join(runtimePaths.configDir, 'providers.json'), 'utf8'),
  );

  assert.equal(providers.selected_provider, 'custom');
  assert.equal(providers.providers.custom.api_key, 'sk-real');
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
  assert.equal(masked.version, 2);
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
          base_url: 'https://example.invalid/v1',
          model: 'gpt-5',
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
    theme_mode: 'dark',
    background_mode: 'balanced',
    action_plan_auto_generate: true,
    voice_base_url: '',
    voice_api_key: '',
    voice_model: 'FunAudioLLM/SenseVoiceSmall',
  });
  assert.deepEqual(providers, {
    version: 2,
    selected_provider: 'openai',
    providers: {
      openai: {
        route: 'openai',
        name: 'openai',
        type: 'openai-compatible',
        enabled: true,
        api_key: 'sk-demo',
        base_url: 'https://example.invalid/v1',
        model: 'gpt-5',
        models: ['gpt-5'],
        last_refreshed_at: null,
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

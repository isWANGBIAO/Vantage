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
  sanitizeProviderConfig,
  saveSettingsPayload,
  saveOnboardingCompletion,
} = require('./onboardingConfig.cjs');

test('sanitizeProviderConfig removes deprecated provider models', () => {
  const removedName = ['gemi', 'ni'].join('');
  const sanitized = sanitizeProviderConfig({
    selected_provider: 'secondary',
    providers: {
      secondary: {
        name: 'Secondary',
        api_key: 'sk-secondary',
        base_url: 'http://127.0.0.1:8045/v1',
        model: `${removedName}-pro`,
        models: [`${removedName}-pro`],
      },
      mixed: {
        name: 'Mixed',
        api_key: 'sk-mixed',
        base_url: 'http://127.0.0.1:8317/v1',
        model: `${removedName}-flash`,
        models: [`${removedName}-flash`, 'gpt-5.5'],
      },
    },
  });

  assert.equal(sanitized.selected_provider, 'mixed');
  assert.deepEqual(Object.keys(sanitized.providers), ['mixed']);
  assert.equal(sanitized.providers.mixed.model, 'gpt-5.5');
  assert.deepEqual(sanitized.providers.mixed.models, ['gpt-5.5']);
  assert.equal(JSON.stringify(sanitized).toLowerCase().includes(removedName), false);
});

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

test('loadSettings defaults formal settings without background mode', () => {
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
  assert.equal(Object.hasOwn(state.settings, 'backgroundMode'), false);
  assert.equal(state.settings.actionPlanAutoGenerate, true);
  assert.equal(state.settings.voiceProviderMode, 'inherit_ai');
  assert.equal(state.settings.voiceBaseUrl, '');
  assert.equal(state.settings.voiceApiKey, '');
  assert.equal(state.settings.voiceModel, 'FunAudioLLM/SenseVoiceSmall');
  assert.deepEqual(state.settings.voiceModels, ['FunAudioLLM/SenseVoiceSmall']);
  assert.equal(state.settings.voiceLastRefreshedAt, null);
  assert.equal(state.settings.imageProviderMode, 'inherit_ai');
  assert.equal(state.settings.imageBaseUrl, '');
  assert.equal(state.settings.imageApiKey, '');
  assert.equal(state.settings.imageModel, '');
  assert.deepEqual(state.settings.imageModels, []);
  assert.equal(state.settings.imageLastRefreshedAt, null);
  assert.equal(state.app.buildDate, null);
  assert.equal(state.app.buildCommit, null);
  assert.equal(state.app.version, '1.2.3');
  assert.equal(state.app.mode, 'packaged');
  assert.equal(state.systemLocale, 'zh-CN');
});

test('loadSettings migrates every v1 background mode to v2 without losing other settings', () => {
  for (const legacyMode of ['balanced', 'prewarm', 'power_saver']) {
    const root = mkdtempSync(path.join(tmpdir(), 'vantage-settings-v1-'));
    const runtimePaths = {
      configDir: path.join(root, 'config'),
      migrationDir: path.join(root, 'migration'),
      dataDir: path.join(root, 'data'),
    };
    mkdirSync(runtimePaths.configDir, { recursive: true });
    writeFileSync(
      path.join(runtimePaths.configDir, 'settings.json'),
      JSON.stringify({
        version: 1,
        onboarding_completed: true,
        launch_at_login: true,
        display_language: 'zh-CN',
        theme: 'light',
        theme_mode: 'auto',
        background_mode: legacyMode,
        action_plan_auto_generate: false,
        voice_provider_mode: 'custom',
        voice_base_url: 'https://voice.example.invalid/v1',
        voice_api_key: 'sk-voice',
        voice_model: 'sensevoice',
        voice_models: ['sensevoice', 'sensevoice-large'],
      }),
      'utf8',
    );

    const state = buildSettingsState({ runtimePaths, projectRoot: root });
    const persisted = JSON.parse(
      readFileSync(path.join(runtimePaths.configDir, 'settings.json'), 'utf8'),
    );

    assert.equal(Object.hasOwn(state.settings, 'backgroundMode'), false);
    assert.equal(state.settings.displayLanguage, 'zh-CN');
    assert.equal(state.settings.themeMode, 'auto');
    assert.equal(state.settings.launchAtLogin, true);
    assert.equal(state.settings.actionPlanAutoGenerate, false);
    assert.equal(state.settings.voiceProviderMode, 'custom');
    assert.deepEqual(state.settings.voiceModels, ['sensevoice', 'sensevoice-large']);
    assert.equal(persisted.version, 2);
    assert.equal(Object.hasOwn(persisted, 'background_mode'), false);
    assert.equal(persisted.theme_mode, 'auto');
    assert.equal(persisted.action_plan_auto_generate, false);
    assert.deepEqual(persisted.voice_models, ['sensevoice', 'sensevoice-large']);
  }
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
      voiceProviderMode: 'custom',
      voiceBaseUrl: 'https://voice.example.invalid/v1',
      voiceApiKey: 'sk-voice-secret',
      voiceModel: 'sensevoice',
      voiceModels: ['sensevoice', 'sensevoice-large'],
      voiceLastRefreshedAt: '2026-05-03T12:00:00+08:00',
      imageProviderMode: 'custom',
      imageBaseUrl: 'https://images.example.invalid/v1',
      imageApiKey: 'sk-image-secret',
      imageModel: 'image-model',
      imageModels: ['image-model', 'image-large'],
      imageLastRefreshedAt: '2026-05-03T12:01:00+08:00',
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
  assert.equal(Object.hasOwn(state.settings, 'backgroundMode'), false);
  assert.equal(state.settings.actionPlanAutoGenerate, false);
  assert.equal(state.settings.voiceProviderMode, 'custom');
  assert.equal(state.settings.voiceBaseUrl, 'https://voice.example.invalid/v1');
  assert.equal(state.settings.voiceApiKey, '********');
  assert.equal(state.settings.voiceHasApiKey, true);
  assert.equal(state.settings.voiceModel, 'sensevoice');
  assert.deepEqual(state.settings.voiceModels, ['sensevoice', 'sensevoice-large']);
  assert.equal(state.settings.voiceLastRefreshedAt, '2026-05-03T12:00:00+08:00');
  assert.equal(state.settings.imageProviderMode, 'custom');
  assert.equal(state.settings.imageBaseUrl, 'https://images.example.invalid/v1');
  assert.equal(state.settings.imageApiKey, '********');
  assert.equal(state.settings.imageHasApiKey, true);
  assert.equal(state.settings.imageModel, 'image-model');
  assert.deepEqual(state.settings.imageModels, ['image-model', 'image-large']);
  assert.equal(state.settings.imageLastRefreshedAt, '2026-05-03T12:01:00+08:00');
  assert.equal(state.provider.providers.cliproxyapi.api_key, '********');
  assert.deepEqual(settings, {
    version: 2,
    onboarding_completed: false,
    launch_at_login: true,
    display_language: 'en-US',
    theme: 'light',
    theme_mode: 'auto',
    action_plan_auto_generate: false,
    voice_provider_mode: 'custom',
    voice_base_url: 'https://voice.example.invalid/v1',
    voice_api_key: 'sk-voice-secret',
    voice_model: 'sensevoice',
    voice_models: ['sensevoice', 'sensevoice-large'],
    voice_last_refreshed_at: '2026-05-03T12:00:00+08:00',
    image_provider_mode: 'custom',
    image_base_url: 'https://images.example.invalid/v1',
    image_api_key: 'sk-image-secret',
    image_model: 'image-model',
    image_models: ['image-model', 'image-large'],
    image_last_refreshed_at: '2026-05-03T12:01:00+08:00',
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
    version: 2,
    onboarding_completed: true,
    launch_at_login: true,
    display_language: 'en-US',
    theme: 'dark',
    theme_mode: 'dark',
    action_plan_auto_generate: true,
    voice_base_url: '',
    voice_api_key: '',
    voice_model: 'FunAudioLLM/SenseVoiceSmall',
    image_base_url: '',
    image_api_key: '',
    image_model: '',
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

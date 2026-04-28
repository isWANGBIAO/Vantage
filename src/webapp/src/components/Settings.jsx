import { useEffect, useMemo, useState } from 'react';
import {
  Check,
  Copy,
  Eye,
  EyeOff,
  FolderOpen,
  Info,
  MonitorCog,
  Plus,
  RefreshCw,
  Save,
  Star,
  Trash2,
} from 'lucide-react';
import { fetchBackendJson } from '../utils/backendRequest';
import { loadSettingsState, openSettingsPath, saveSettingsState } from '../utils/settingsState';
import { useDisplayLanguage } from '../context/DisplayLanguageContext.jsx';

const SECTION_ORDER = [
  { key: 'general', labelKey: 'settings.section.general' },
  { key: 'ai_provider', labelKey: 'settings.section.ai_provider' },
  { key: 'voice_provider', labelKey: 'settings.section.voice_provider' },
  { key: 'data_logs', labelKey: 'settings.section.data_logs' },
  { key: 'performance', labelKey: 'settings.section.performance' },
  { key: 'about', labelKey: 'settings.section.about' },
];

const LANGUAGE_OPTIONS = [
  { value: 'system', labelKey: 'app.language.follow_system' },
  { value: 'zh-CN', labelKey: 'app.language.zh_cn' },
  { value: 'en-US', labelKey: 'app.language.en_us' },
];

const THEME_OPTIONS = [
  { value: 'auto', labelKey: 'settings.general.theme_auto' },
  { value: 'dark', labelKey: 'settings.general.theme_dark' },
  { value: 'light', labelKey: 'settings.general.theme_light' },
];

const DEFAULT_VOICE_MODEL = 'FunAudioLLM/SenseVoiceSmall';

const BACKGROUND_MODE_OPTIONS = [
  { value: 'balanced', labelKey: 'settings.performance.balanced' },
  { value: 'prewarm', labelKey: 'settings.performance.prewarm' },
  { value: 'power_saver', labelKey: 'settings.performance.power_saver' },
];

const PATH_LABELS = [
  ['config', 'settings.paths.config'],
  ['history', 'settings.paths.history'],
  ['logs', 'settings.paths.logs'],
  ['plots', 'settings.paths.plots'],
  ['cache', 'settings.paths.cache'],
  ['runtime', 'settings.paths.runtime'],
  ['data', 'settings.paths.data'],
];

function normalizeProviderModels(provider) {
  const seen = new Set();
  const models = [];
  const pushModel = (value) => {
    const normalized = typeof value === 'string' ? value.trim() : '';
    if (!normalized || seen.has(normalized)) {
      return;
    }
    seen.add(normalized);
    models.push(normalized);
  };

  pushModel(provider?.model);
  if (Array.isArray(provider?.models)) {
    provider.models.forEach(pushModel);
  }
  return models;
}

function createProviderEntry(route, entry = {}) {
  const normalizedRoute = typeof route === 'string' && route.trim() ? route.trim() : 'custom';
  const model = typeof entry.model === 'string' ? entry.model.trim() : '';
  return {
    route: normalizedRoute,
    name: typeof entry.name === 'string' && entry.name.trim() ? entry.name.trim() : normalizedRoute,
    type: entry.type === 'openai-compatible' ? entry.type : 'openai-compatible',
    enabled: typeof entry.enabled === 'boolean' ? entry.enabled : true,
    api_key: typeof entry.api_key === 'string' ? entry.api_key : '',
    base_url: typeof entry.base_url === 'string' ? entry.base_url : '',
    model,
    models: normalizeProviderModels({ ...entry, model }),
    last_refreshed_at: typeof entry.last_refreshed_at === 'string' ? entry.last_refreshed_at : null,
    has_api_key: Boolean(entry.has_api_key),
  };
}

function normalizeProviderConfigForForm(providerConfig) {
  const providers = {};
  const rawProviders = providerConfig?.providers && typeof providerConfig.providers === 'object'
    ? providerConfig.providers
    : {};

  for (const [route, entry] of Object.entries(rawProviders)) {
    const normalizedRoute = typeof route === 'string' && route.trim() ? route.trim() : '';
    if (!normalizedRoute) {
      continue;
    }
    providers[normalizedRoute] = createProviderEntry(normalizedRoute, entry);
  }

  const providerRoutes = Object.keys(providers);
  const selectedProvider = (
    providerConfig?.selected_provider && providers[providerConfig.selected_provider]
      ? providerConfig.selected_provider
      : providerRoutes[0]
  ) || 'custom';

  if (providerRoutes.length === 0) {
    providers.custom = createProviderEntry('custom');
  }

  return {
    version: 2,
    selected_provider: selectedProvider,
    providers,
  };
}

function buildProviderRoute(baseRoute, providers) {
  const normalizedBase = baseRoute || 'custom';
  if (!providers[normalizedBase]) {
    return normalizedBase;
  }

  let index = 2;
  while (providers[`${normalizedBase}_${index}`]) {
    index += 1;
  }
  return `${normalizedBase}_${index}`;
}

function SettingsRow({ label, children }) {
  return (
    <div className="settings-row">
      <span className="settings-row-label">{label}</span>
      <span className="settings-row-control">{children}</span>
    </div>
  );
}

export default function Settings({ currentTheme = 'dark', currentThemeMode = 'dark', onSettingsApplied }) {
  const { displayLanguage, setDisplayLanguage, t } = useDisplayLanguage();
  const [activeSection, setActiveSection] = useState('general');
  const [activeProviderRoute, setActiveProviderRoute] = useState('custom');
  const [providerRouteDraft, setProviderRouteDraft] = useState('custom');
  const [state, setState] = useState(null);
  const [form, setForm] = useState({
    displayLanguage,
    theme: currentTheme,
    themeMode: currentThemeMode,
    launchAtLogin: false,
    backgroundMode: 'balanced',
    voiceBaseUrl: '',
    voiceApiKey: '',
    voiceModel: DEFAULT_VOICE_MODEL,
    voiceHasApiKey: false,
    providerConfig: normalizeProviderConfigForForm(null),
  });
  const [showApiKey, setShowApiKey] = useState(false);
  const [showVoiceApiKey, setShowVoiceApiKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [refreshingModels, setRefreshingModels] = useState(false);
  const [saveStatus, setSaveStatus] = useState('');

  useEffect(() => {
    let cancelled = false;

    async function loadState() {
      const [nextState, modelCatalog] = await Promise.all([
        loadSettingsState(),
        fetchBackendJson('/api/llm_models', { retryPolicy: 'load' }).catch(() => null),
      ]);
      if (cancelled) {
        return;
      }

      const providerConfig = normalizeProviderConfigForForm(nextState.provider);
      const selectedProvider = providerConfig.providers[providerConfig.selected_provider];
      if (!selectedProvider.model && typeof modelCatalog?.default_model === 'string') {
        providerConfig.providers[providerConfig.selected_provider] = {
          ...selectedProvider,
          model: modelCatalog.default_model,
          models: normalizeProviderModels({ ...selectedProvider, model: modelCatalog.default_model }),
        };
      }
      setState(nextState);
      setActiveProviderRoute(providerConfig.selected_provider);
      setProviderRouteDraft(providerConfig.selected_provider);
      setForm({
        displayLanguage: nextState.settings.displayLanguage || displayLanguage,
        theme: nextState.settings.theme || currentTheme,
        themeMode: nextState.settings.themeMode || nextState.settings.theme || currentThemeMode,
        launchAtLogin: Boolean(nextState.settings.launchAtLogin),
        backgroundMode: nextState.settings.backgroundMode || 'balanced',
        voiceBaseUrl: nextState.settings.voiceBaseUrl || '',
        voiceApiKey: nextState.settings.voiceApiKey || '',
        voiceModel: nextState.settings.voiceModel || DEFAULT_VOICE_MODEL,
        voiceHasApiKey: Boolean(nextState.settings.voiceHasApiKey),
        providerConfig,
      });
    }

    void loadState();

    return () => {
      cancelled = true;
    };
  }, [currentTheme, currentThemeMode, displayLanguage]);

  const providerRoutes = Object.keys(form.providerConfig.providers);
  const currentProviderRoute = form.providerConfig.providers[activeProviderRoute]
    ? activeProviderRoute
    : form.providerConfig.selected_provider;
  const currentProvider = form.providerConfig.providers[currentProviderRoute] || createProviderEntry(currentProviderRoute);

  const diagnosticsText = useMemo(() => {
    if (!state) {
      return '';
    }

    return [
      `Vantage ${state.app.version}`,
      `mode=${state.app.mode}`,
      `backendRuntime=${state.app.backendRuntimePath || ''}`,
      `dataDir=${state.app.dataDir || ''}`,
      `language=${form.displayLanguage}`,
      `theme=${form.theme}`,
      `themeMode=${form.themeMode}`,
      `backgroundMode=${form.backgroundMode}`,
      `voiceBaseUrl=${form.voiceBaseUrl || ''}`,
      `voiceModel=${form.voiceModel || ''}`,
      `provider=${form.providerConfig.selected_provider || ''}`,
    ].join('\n');
  }, [
    form.backgroundMode,
    form.displayLanguage,
    form.providerConfig.selected_provider,
    form.theme,
    form.themeMode,
    form.voiceBaseUrl,
    form.voiceModel,
    state,
  ]);

  const updateProviderConfig = (updater) => {
    setForm((prev) => ({
      ...prev,
      providerConfig: updater(prev.providerConfig),
    }));
  };

  const updateProvider = (key, value) => {
    updateProviderConfig((providerConfig) => {
      const route = currentProviderRoute;
      const provider = createProviderEntry(route, providerConfig.providers[route]);
      const nextProvider = {
        ...provider,
        [key]: value,
      };
      if (key === 'model') {
        nextProvider.models = normalizeProviderModels(nextProvider);
      }
      return {
        ...providerConfig,
        providers: {
          ...providerConfig.providers,
          [route]: createProviderEntry(route, nextProvider),
        },
      };
    });
  };

  const commitProviderRoute = () => {
    const normalizedRoute = providerRouteDraft.trim();
    if (!normalizedRoute || normalizedRoute === currentProviderRoute) {
      setProviderRouteDraft(currentProviderRoute);
      return;
    }

    const providers = { ...form.providerConfig.providers };
    const current = createProviderEntry(currentProviderRoute, providers[currentProviderRoute]);
    delete providers[currentProviderRoute];
    const safeRoute = buildProviderRoute(normalizedRoute, providers);
    providers[safeRoute] = createProviderEntry(safeRoute, {
      ...current,
      route: safeRoute,
      name: current.name === currentProviderRoute ? safeRoute : current.name,
    });
    const nextProviderConfig = {
      ...form.providerConfig,
      selected_provider: form.providerConfig.selected_provider === currentProviderRoute
        ? safeRoute
        : form.providerConfig.selected_provider,
      providers,
    };
    setForm((prev) => ({
      ...prev,
      providerConfig: nextProviderConfig,
    }));
    setActiveProviderRoute(safeRoute);
    setProviderRouteDraft(safeRoute);
  };

  const addProvider = () => {
    const route = buildProviderRoute('custom', form.providerConfig.providers);
    const nextProviderConfig = {
      ...form.providerConfig,
      selected_provider: form.providerConfig.selected_provider || route,
      providers: {
        ...form.providerConfig.providers,
        [route]: createProviderEntry(route),
      },
    };
    setForm((prev) => ({
      ...prev,
      providerConfig: nextProviderConfig,
    }));
    setActiveProviderRoute(route);
    setProviderRouteDraft(route);
  };

  const deleteProvider = (route) => {
    const providers = { ...form.providerConfig.providers };
    delete providers[route];
    const routes = Object.keys(providers);
    if (routes.length === 0) {
      providers.custom = createProviderEntry('custom');
      routes.push('custom');
    }
    const nextSelected = form.providerConfig.selected_provider === route
      ? routes[0]
      : form.providerConfig.selected_provider;
    const nextActive = route === currentProviderRoute ? nextSelected : currentProviderRoute;
    const nextProviderConfig = {
      ...form.providerConfig,
      selected_provider: nextSelected,
      providers,
    };
    setForm((prev) => ({
      ...prev,
      providerConfig: nextProviderConfig,
    }));
    setActiveProviderRoute(nextActive);
    setProviderRouteDraft(nextActive);
  };

  const setDefaultProvider = (route) => {
    updateProviderConfig((providerConfig) => ({
      ...providerConfig,
      selected_provider: route,
    }));
  };

  const toggleProviderEnabled = (route) => {
    updateProviderConfig((providerConfig) => ({
      ...providerConfig,
      providers: {
        ...providerConfig.providers,
        [route]: createProviderEntry(route, {
          ...providerConfig.providers[route],
          enabled: providerConfig.providers[route]?.enabled === false,
        }),
      },
    }));
  };

  const refreshProviderModels = async () => {
    setRefreshingModels(true);
    setSaveStatus('');
    try {
      const payload = await fetchBackendJson('/api/llm_models/discover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          route: currentProviderRoute,
          base_url: currentProvider.base_url,
          api_key: currentProvider.api_key,
          type: currentProvider.type,
        }),
        retryPolicy: 'mutation',
      });
      const discoveredModels = Array.isArray(payload?.models) ? payload.models : [];
      updateProviderConfig((providerConfig) => {
        const provider = createProviderEntry(currentProviderRoute, providerConfig.providers[currentProviderRoute]);
        const nextModel = provider.model || discoveredModels[0] || '';
        return {
          ...providerConfig,
          providers: {
            ...providerConfig.providers,
            [currentProviderRoute]: createProviderEntry(currentProviderRoute, {
              ...provider,
              model: nextModel,
              models: discoveredModels.length > 0 ? discoveredModels : provider.models,
              last_refreshed_at: new Date().toISOString(),
            }),
          },
        };
      });
      setSaveStatus(t('settings.provider.refresh_success', { count: discoveredModels.length }));
    } catch (error) {
      setSaveStatus(t('settings.provider.refresh_failed', { error: error.message || String(error) }));
    } finally {
      setRefreshingModels(false);
    }
  };

  const updateThemeMode = (themeMode) => {
    const nextTheme = themeMode === 'auto' ? currentTheme : themeMode;
    setForm((prev) => ({ ...prev, themeMode, theme: nextTheme }));
    onSettingsApplied?.({ themeMode, theme: nextTheme });
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveStatus('');
    try {
      const savedState = await saveSettingsState(form);
      const providerConfig = normalizeProviderConfigForForm(savedState.provider);
      setState(savedState);
      setActiveProviderRoute(providerConfig.selected_provider);
      setProviderRouteDraft(providerConfig.selected_provider);
      setForm((prev) => ({
        ...prev,
        displayLanguage: savedState.settings.displayLanguage,
        theme: savedState.settings.theme,
        themeMode: savedState.settings.themeMode,
        launchAtLogin: Boolean(savedState.settings.launchAtLogin),
        backgroundMode: savedState.settings.backgroundMode,
        voiceBaseUrl: savedState.settings.voiceBaseUrl || '',
        voiceApiKey: savedState.settings.voiceApiKey || '',
        voiceModel: savedState.settings.voiceModel || DEFAULT_VOICE_MODEL,
        voiceHasApiKey: Boolean(savedState.settings.voiceHasApiKey),
        providerConfig,
      }));
      await setDisplayLanguage(savedState.settings.displayLanguage);
      onSettingsApplied?.(savedState.settings);
      window.dispatchEvent(new CustomEvent('vantage:settings-updated', {
        detail: savedState.settings,
      }));
      const modelCatalog = await fetchBackendJson('/api/llm_models', { retryPolicy: 'poll' }).catch(() => null);
      window.dispatchEvent(new CustomEvent('vantage:llm-models-updated', {
        detail: modelCatalog || {
          models: [],
          default_model: providerConfig.providers[providerConfig.selected_provider]?.model || null,
          default_provider_route: providerConfig.selected_provider,
          providers: [],
          model_options: [],
        },
      }));
      setSaveStatus(t('settings.save.saved'));
    } catch (error) {
      setSaveStatus(t('settings.save.failed', { error: error.message || String(error) }));
    } finally {
      setSaving(false);
    }
  };

  const openPath = async (pathKey) => {
    const opened = await openSettingsPath(pathKey);
    if (!opened) {
      setSaveStatus(t('settings.paths.open_failed'));
    }
  };

  const copyDiagnostics = async () => {
    if (!diagnosticsText) {
      return;
    }
    await navigator.clipboard?.writeText(diagnosticsText);
    setSaveStatus(t('settings.about.copied'));
  };

  const renderGeneral = () => (
    <section className="settings-section">
      <SettingsRow label={t('settings.general.language')}>
        <select
          className="settings-input"
          value={form.displayLanguage}
          onChange={(event) => setForm((prev) => ({ ...prev, displayLanguage: event.target.value }))}
        >
          {LANGUAGE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {t(option.labelKey)}
            </option>
          ))}
        </select>
      </SettingsRow>
      <SettingsRow label={t('settings.general.theme')}>
        <div className="settings-segmented">
          {THEME_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={form.themeMode === option.value ? 'is-active' : ''}
              onClick={() => updateThemeMode(option.value)}
            >
              {t(option.labelKey)}
            </button>
          ))}
        </div>
      </SettingsRow>
      <label className="settings-checkbox-row">
        <input
          type="checkbox"
          checked={form.launchAtLogin}
          onChange={(event) => setForm((prev) => ({ ...prev, launchAtLogin: event.target.checked }))}
        />
        <span>{t('settings.general.launch_at_login')}</span>
      </label>
    </section>
  );

  const renderProvider = () => (
    <section className="settings-section settings-provider-section">
      <div className="settings-provider-layout">
        <div className="settings-provider-list">
          <div className="settings-provider-list-header">
            <span>{t('settings.provider.providers')}</span>
            <button type="button" className="settings-icon-button" onClick={addProvider} title={t('settings.provider.add')}>
              <Plus size={16} />
            </button>
          </div>
          {providerRoutes.map((route) => {
            const provider = form.providerConfig.providers[route];
            return (
              <button
                key={route}
                type="button"
                className={`settings-provider-item${route === currentProviderRoute ? ' is-active' : ''}`}
                onClick={() => {
                  setActiveProviderRoute(route);
                  setProviderRouteDraft(route);
                }}
              >
                <span className="settings-provider-name">{provider.name || route}</span>
                <span className="settings-provider-meta">
                  {provider.enabled ? t('settings.provider.enabled') : t('settings.provider.disabled')}
                  {form.providerConfig.selected_provider === route ? ` | ${t('settings.provider.default')}` : ''}
                </span>
              </button>
            );
          })}
        </div>

        <div className="settings-provider-editor">
          <div className="settings-provider-editor-actions">
            <button
              type="button"
              className="secondary-button settings-small-button"
              onClick={() => setDefaultProvider(currentProviderRoute)}
            >
              <Star size={15} />
              {t('settings.provider.set_default')}
            </button>
            <button
              type="button"
              className="secondary-button settings-small-button"
              onClick={() => toggleProviderEnabled(currentProviderRoute)}
            >
              {currentProvider.enabled ? t('settings.provider.disable') : t('settings.provider.enable')}
            </button>
            <button
              type="button"
              className="secondary-button settings-small-button danger"
              onClick={() => deleteProvider(currentProviderRoute)}
            >
              <Trash2 size={15} />
              {t('settings.provider.delete')}
            </button>
          </div>
          <SettingsRow label={t('settings.provider.name')}>
            <input
              className="settings-input"
              value={currentProvider.name}
              onChange={(event) => updateProvider('name', event.target.value)}
            />
          </SettingsRow>
          <SettingsRow label={t('settings.provider.route')}>
            <input
              className="settings-input"
              value={providerRouteDraft}
              onChange={(event) => setProviderRouteDraft(event.target.value)}
              onBlur={commitProviderRoute}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.currentTarget.blur();
                }
              }}
            />
          </SettingsRow>
          <SettingsRow label={t('settings.provider.base_url')}>
            <input
              className="settings-input"
              value={currentProvider.base_url}
              onChange={(event) => updateProvider('base_url', event.target.value)}
            />
          </SettingsRow>
          <SettingsRow label={t('settings.provider.api_key')}>
            <span className="settings-secret-input">
              <input
                className="settings-input"
                type={showApiKey ? 'text' : 'password'}
                value={currentProvider.api_key}
                onChange={(event) => updateProvider('api_key', event.target.value)}
              />
              <button
                type="button"
                className="settings-icon-button"
                onClick={() => setShowApiKey((prev) => !prev)}
                title={t(showApiKey ? 'settings.provider.hide_key' : 'settings.provider.show_key')}
              >
                {showApiKey ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </span>
          </SettingsRow>
          <SettingsRow label={t('settings.provider.model')}>
            <span className="settings-secret-input">
              <input
                className="settings-input settings-provider-model-select"
                list={`settings-models-${currentProviderRoute}`}
                value={currentProvider.model}
                onChange={(event) => updateProvider('model', event.target.value)}
              />
              <datalist id={`settings-models-${currentProviderRoute}`}>
                {currentProvider.models.map((model) => (
                  <option key={model} value={model} />
                ))}
              </datalist>
              <button
                type="button"
                className="settings-icon-button"
                onClick={refreshProviderModels}
                disabled={refreshingModels}
                title={t('settings.provider.refresh_models')}
              >
                <RefreshCw size={16} />
              </button>
            </span>
          </SettingsRow>
          <div className="settings-status-line">
            <Info size={16} />
            {currentProvider.last_refreshed_at
              ? t('settings.provider.last_refreshed', { value: currentProvider.last_refreshed_at })
              : t('settings.provider.not_refreshed')}
          </div>
        </div>
      </div>
    </section>
  );

  const renderVoiceProvider = () => (
    <section className="settings-section">
      <SettingsRow label={t('settings.voice_provider.base_url')}>
        <input
          className="settings-input"
          value={form.voiceBaseUrl}
          placeholder="https://api.example.com/v1"
          onChange={(event) => setForm((prev) => ({ ...prev, voiceBaseUrl: event.target.value }))}
        />
      </SettingsRow>
      <SettingsRow label={t('settings.voice_provider.api_key')}>
        <span className="settings-secret-input">
          <input
            className="settings-input"
            type={showVoiceApiKey ? 'text' : 'password'}
            value={form.voiceApiKey}
            onChange={(event) => setForm((prev) => ({
              ...prev,
              voiceApiKey: event.target.value,
              voiceHasApiKey: Boolean(event.target.value),
            }))}
          />
          <button
            type="button"
            className="settings-icon-button"
            onClick={() => setShowVoiceApiKey((prev) => !prev)}
            title={t(showVoiceApiKey ? 'settings.provider.hide_key' : 'settings.provider.show_key')}
          >
            {showVoiceApiKey ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        </span>
      </SettingsRow>
      <SettingsRow label={t('settings.voice_provider.model')}>
        <input
          className="settings-input"
          value={form.voiceModel}
          placeholder={DEFAULT_VOICE_MODEL}
          onChange={(event) => setForm((prev) => ({ ...prev, voiceModel: event.target.value }))}
        />
      </SettingsRow>
      <div className="settings-status-line">
        <Info size={16} />
        {t('settings.voice_provider.endpoint_hint')}
      </div>
    </section>
  );

  const renderDataLogs = () => (
    <section className="settings-section">
      <div className="settings-path-grid">
        {PATH_LABELS.map(([pathKey, labelKey]) => (
          <div className="settings-path-row" key={pathKey}>
            <div>
              <div className="settings-path-label">{t(labelKey)}</div>
              <div className="settings-path-value">{state?.runtimePaths?.[pathKey] || '--'}</div>
            </div>
            {['config', 'history', 'logs'].includes(pathKey) ? (
              <button
                type="button"
                className="secondary-button settings-small-button"
                onClick={() => openPath(pathKey)}
              >
                <FolderOpen size={15} />
                {t('settings.paths.open')}
              </button>
            ) : null}
          </div>
        ))}
      </div>
      <div className="settings-status-line">
        <Info size={16} />
        {state?.migration?.completed
          ? t('settings.data_logs.migration_done', { path: state.migration.sourcePath || '--' })
          : t('settings.data_logs.migration_pending')}
      </div>
    </section>
  );

  const renderPerformance = () => (
    <section className="settings-section">
      <SettingsRow label={t('settings.performance.background_mode')}>
        <div className="settings-mode-list">
          {BACKGROUND_MODE_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={form.backgroundMode === option.value ? 'is-active' : ''}
              onClick={() => setForm((prev) => ({ ...prev, backgroundMode: option.value }))}
            >
              <MonitorCog size={16} />
              {t(option.labelKey)}
            </button>
          ))}
        </div>
      </SettingsRow>
    </section>
  );

  const renderAbout = () => (
    <section className="settings-section">
      <div className="settings-about-grid">
        <div>{t('settings.about.version')}</div>
        <strong>{state?.app?.version || '--'}</strong>
        <div>{t('settings.about.mode')}</div>
        <strong>{state?.app?.mode || '--'}</strong>
        <div>{t('settings.about.backend_runtime')}</div>
        <strong>{state?.app?.backendRuntimePath || '--'}</strong>
        <div>{t('settings.about.data_dir')}</div>
        <strong>{state?.app?.dataDir || '--'}</strong>
      </div>
      <div className="settings-inline-actions">
        <button type="button" className="secondary-button" onClick={() => openPath('logs')}>
          <FolderOpen size={15} />
          {t('settings.paths.open_logs')}
        </button>
        <button type="button" className="secondary-button" onClick={copyDiagnostics}>
          <Copy size={15} />
          {t('settings.about.copy_diagnostics')}
        </button>
      </div>
    </section>
  );

  const renderActiveSection = () => {
    if (activeSection === 'general') {
      return renderGeneral();
    }
    if (activeSection === 'ai_provider') {
      return renderProvider();
    }
    if (activeSection === 'voice_provider') {
      return renderVoiceProvider();
    }
    if (activeSection === 'data_logs') {
      return renderDataLogs();
    }
    if (activeSection === 'performance') {
      return renderPerformance();
    }
    return renderAbout();
  };

  return (
    <div className="settings-page">
      <aside className="settings-sidebar">
        {SECTION_ORDER.map((section) => (
          <button
            key={section.key}
            type="button"
            className={activeSection === section.key ? 'is-active' : ''}
            onClick={() => setActiveSection(section.key)}
          >
            {t(section.labelKey)}
          </button>
        ))}
      </aside>
      <div className="settings-content">
        <div className="settings-header">
          <div>
            <p className="settings-eyebrow">{t('settings.title')}</p>
            <h2>{t(SECTION_ORDER.find((section) => section.key === activeSection)?.labelKey || 'settings.title')}</h2>
          </div>
          <button type="button" className="settings-save-button" onClick={handleSave} disabled={saving}>
            {saving ? <Check size={18} /> : <Save size={18} />}
            {saving ? t('settings.save.saving') : t('settings.save.button')}
          </button>
        </div>
        {renderActiveSection()}
        {saveStatus ? <div className="settings-save-status">{saveStatus}</div> : null}
      </div>
    </div>
  );
}

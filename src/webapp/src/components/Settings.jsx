import { useEffect, useMemo, useState } from 'react';
import {
  Check,
  Copy,
  Eye,
  EyeOff,
  FolderOpen,
  Info,
  MonitorCog,
  Save,
} from 'lucide-react';
import { fetchBackendJson } from '../utils/backendRequest';
import { loadSettingsState, openSettingsPath, saveSettingsState } from '../utils/settingsState';
import { useDisplayLanguage } from '../context/DisplayLanguageContext.jsx';

const SECTION_ORDER = [
  { key: 'general', labelKey: 'settings.section.general' },
  { key: 'ai_provider', labelKey: 'settings.section.ai_provider' },
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
  { value: 'dark', labelKey: 'settings.general.theme_dark' },
  { value: 'light', labelKey: 'settings.general.theme_light' },
];

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

function getActiveProvider(providerConfig) {
  const route = providerConfig?.selected_provider || 'cliproxyapi';
  const provider = providerConfig?.providers?.[route] || {};
  return {
    route,
    baseUrl: provider.base_url || '',
    apiKey: provider.api_key || '',
    model: provider.model || '',
  };
}

function buildModelOptions(currentModel, modelList) {
  const options = [];
  const seen = new Set();

  for (const model of [currentModel, ...modelList]) {
    const normalized = typeof model === 'string' ? model.trim() : '';
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    options.push(normalized);
  }

  return options;
}

function SettingsRow({ label, children }) {
  return (
    <div className="settings-row">
      <span className="settings-row-label">{label}</span>
      <span className="settings-row-control">{children}</span>
    </div>
  );
}

export default function Settings({ currentTheme = 'dark', onSettingsApplied }) {
  const { displayLanguage, setDisplayLanguage, t } = useDisplayLanguage();
  const [activeSection, setActiveSection] = useState('general');
  const [state, setState] = useState(null);
  const [form, setForm] = useState({
    displayLanguage,
    theme: currentTheme,
    launchAtLogin: false,
    backgroundMode: 'balanced',
    provider: {
      route: 'cliproxyapi',
      baseUrl: '',
      apiKey: '',
      model: '',
    },
  });
  const [availableModels, setAvailableModels] = useState([]);
  const [showApiKey, setShowApiKey] = useState(false);
  const [saving, setSaving] = useState(false);
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

      const provider = getActiveProvider(nextState.provider);
      const modelList = Array.isArray(modelCatalog?.models) ? modelCatalog.models : [];
      if (!provider.model && typeof modelCatalog?.default_model === 'string') {
        provider.model = modelCatalog.default_model;
      }
      setState(nextState);
      setAvailableModels(buildModelOptions(provider.model, modelList));
      setForm({
        displayLanguage: nextState.settings.displayLanguage || displayLanguage,
        theme: nextState.settings.theme || currentTheme,
        launchAtLogin: Boolean(nextState.settings.launchAtLogin),
        backgroundMode: nextState.settings.backgroundMode || 'balanced',
        provider,
      });
    }

    void loadState();

    return () => {
      cancelled = true;
    };
  }, [currentTheme, displayLanguage]);

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
      `backgroundMode=${form.backgroundMode}`,
    ].join('\n');
  }, [form.backgroundMode, form.displayLanguage, form.theme, state]);

  const updateProvider = (key, value) => {
    setForm((prev) => ({
      ...prev,
      provider: {
        ...prev.provider,
        [key]: value,
      },
    }));
  };

  const updateTheme = (theme) => {
    setForm((prev) => ({ ...prev, theme }));
    onSettingsApplied?.({ theme });
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveStatus('');
    try {
      const savedState = await saveSettingsState(form);
      setState(savedState);
      await setDisplayLanguage(savedState.settings.displayLanguage);
      onSettingsApplied?.(savedState.settings);
      const modelCatalog = await fetchBackendJson('/api/llm_models', { retryPolicy: 'poll' }).catch(() => null);
      const modelList = Array.isArray(modelCatalog?.models) ? modelCatalog.models : [];
      setAvailableModels(buildModelOptions(savedState.provider?.providers?.[savedState.provider?.selected_provider]?.model, modelList));
      if (form.provider.model) {
        localStorage.setItem('preferred_llm_model', form.provider.model);
      }
      window.dispatchEvent(new CustomEvent('vantage:llm-models-updated', {
        detail: modelCatalog || {
          models: buildModelOptions(form.provider.model, []),
          default_model: form.provider.model,
          providers: [],
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
              className={form.theme === option.value ? 'is-active' : ''}
              onClick={() => updateTheme(option.value)}
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
    <section className="settings-section">
      <SettingsRow label={t('settings.provider.route')}>
        <input
          className="settings-input"
          value={form.provider.route}
          onChange={(event) => updateProvider('route', event.target.value)}
        />
      </SettingsRow>
      <SettingsRow label={t('settings.provider.base_url')}>
        <input
          className="settings-input"
          value={form.provider.baseUrl}
          onChange={(event) => updateProvider('baseUrl', event.target.value)}
        />
      </SettingsRow>
      <SettingsRow label={t('settings.provider.api_key')}>
        <span className="settings-secret-input">
          <input
            className="settings-input"
            type={showApiKey ? 'text' : 'password'}
            value={form.provider.apiKey}
            onChange={(event) => updateProvider('apiKey', event.target.value)}
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
        <select
          className="settings-input settings-provider-model-select"
          value={form.provider.model}
          onChange={(event) => updateProvider('model', event.target.value)}
        >
          {availableModels.length === 0 ? (
            <option value={form.provider.model}>{form.provider.model || '--'}</option>
          ) : null}
          {availableModels.map((model) => (
            <option key={model} value={model}>
              {model}
            </option>
          ))}
        </select>
      </SettingsRow>
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

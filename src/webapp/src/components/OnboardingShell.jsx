import { useMemo, useState } from 'react';
import { useDisplayLanguage } from '../context/DisplayLanguageContext.jsx';

const STEP_ORDER = ['welcome', 'provider', 'migration', 'complete'];

const DISPLAY_LANGUAGE_FALLBACKS = {
  system: 'Follow System',
  'zh-CN': 'Simplified Chinese',
  'en-US': 'English',
};

function StepCard({ label, title, isActive, isDone }) {
  return (
    <div
      className={`onboarding-step-card ${isActive ? 'is-active' : ''} ${isDone ? 'is-done' : ''}`}
      aria-current={isActive ? 'step' : undefined}
    >
      <div className="onboarding-step-index">{label}</div>
      <div>{title}</div>
    </div>
  );
}

function Field({ label, children, hint }) {
  return (
    <label className="onboarding-field">
      <span className="onboarding-field-label">{label}</span>
      {children}
      {hint ? <span className="onboarding-field-hint">{hint}</span> : null}
    </label>
  );
}

export default function OnboardingShell({
  displayLanguage = 'system',
  initialLaunchAtLogin = false,
  initialLegacyRoot = null,
  initialProviderConfigured = false,
  initialMigrationCompleted = false,
  onComplete,
  onDisplayLanguageChange,
  onPickLegacyRoot,
}) {
  const { languageOptions, t } = useDisplayLanguage();
  const [stepIndex, setStepIndex] = useState(0);
  const [chatSetupSkipped, setChatSetupSkipped] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState(initialProviderConfigured ? 'openai' : 'openai');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('');
  const [launchAtLogin, setLaunchAtLogin] = useState(initialLaunchAtLogin);
  const [importLegacyData, setImportLegacyData] = useState(Boolean(initialLegacyRoot) || initialMigrationCompleted);
  const [legacyRoot, setLegacyRoot] = useState(initialLegacyRoot || '');
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState('');

  const currentStep = STEP_ORDER[stepIndex];
  const appLayoutClassName =
    typeof window !== 'undefined' && window.electronAPI
      ? 'app-layout app-layout--electron'
      : 'app-layout';

  const stepContent = useMemo(() => ({
    welcome: {
      eyebrow: t('onboarding.welcome.eyebrow'),
      title: t('onboarding.welcome.title'),
      description: t('onboarding.welcome.description'),
      bullets: [
        t('onboarding.welcome.bullet_1'),
        t('onboarding.welcome.bullet_2'),
        t('onboarding.welcome.bullet_3'),
      ],
    },
    provider: {
      eyebrow: t('onboarding.provider.eyebrow'),
      title: t('onboarding.provider.title'),
      description: t('onboarding.provider.description'),
      bullets: [
        t('onboarding.provider.bullet_1'),
        t('onboarding.provider.bullet_2'),
        t('onboarding.provider.bullet_3'),
      ],
    },
    migration: {
      eyebrow: t('onboarding.migration.eyebrow'),
      title: t('onboarding.migration.title'),
      description: t('onboarding.migration.description'),
      bullets: [
        t('onboarding.migration.bullet_1'),
        t('onboarding.migration.bullet_2'),
        t('onboarding.migration.bullet_3'),
      ],
    },
    complete: {
      eyebrow: t('onboarding.complete.eyebrow'),
      title: t('onboarding.complete.title'),
      description: t('onboarding.complete.description'),
      bullets: [
        t('onboarding.complete.bullet_1'),
        t('onboarding.complete.bullet_2'),
        t('onboarding.complete.bullet_3'),
      ],
    },
  }), [t]);

  const currentStepContent = stepContent[currentStep];

  const stepCards = useMemo(
    () =>
      STEP_ORDER.map((step, index) => ({
        id: step,
        label: `${index + 1}`,
        title: stepContent[step].title,
      })),
    [stepContent],
  );

  const handleBack = () => {
    setSaveError('');
    setStepIndex((current) => Math.max(current - 1, 0));
  };

  const handleContinue = async () => {
    setSaveError('');

    if (currentStep === 'complete') {
      try {
        setIsSaving(true);
        await onComplete({
          launchAtLogin,
          selectedProvider,
          baseUrl,
          apiKey,
          model,
          displayLanguage,
          importLegacyData,
          legacyRoot,
          skipChatSetup: chatSetupSkipped,
        });
      } catch (error) {
        setSaveError(error?.message || t('onboarding.error.finish_failed'));
      } finally {
        setIsSaving(false);
      }
      return;
    }

    setStepIndex((current) => Math.min(current + 1, STEP_ORDER.length - 1));
  };

  const handleSkipChatSetup = () => {
    setChatSetupSkipped(true);
    setStepIndex(STEP_ORDER.indexOf('migration'));
  };

  const handlePickLegacyRoot = async () => {
    setSaveError('');
    const nextRoot = await onPickLegacyRoot();
    if (nextRoot) {
      setLegacyRoot(nextRoot);
      setImportLegacyData(true);
    }
  };

  return (
    <div className={appLayoutClassName}>
      <main className="app-container onboarding-page">
        <section className="glass-panel onboarding-shell">
          <div className="onboarding-shell-header">
            <div>
              <div className="onboarding-eyebrow">{currentStepContent.eyebrow}</div>
              <h1 className="onboarding-title">{currentStepContent.title}</h1>
              <p className="onboarding-description">{currentStepContent.description}</p>
            </div>
            <div className="onboarding-progress-chip">
              {t('onboarding.progress', { current: stepIndex + 1, total: STEP_ORDER.length })}
            </div>
          </div>

          <div className="onboarding-content-grid">
            <aside className="onboarding-sidebar">
              {stepCards.map((step, index) => (
                <StepCard
                  key={step.id}
                  label={step.label}
                  title={step.title}
                  isActive={index === stepIndex}
                  isDone={index < stepIndex}
                />
              ))}
            </aside>

            <div className="onboarding-stage">
              <div className="onboarding-panel glass-panel">
                <ul className="onboarding-bullet-list">
                  {currentStepContent.bullets.map((bullet) => (
                    <li key={bullet}>{bullet}</li>
                  ))}
                </ul>

                {currentStep === 'welcome' ? (
                  <div className="onboarding-form-grid">
                    <Field label={t('onboarding.field.display_language')}>
                      <select
                        className="onboarding-input"
                        value={displayLanguage}
                        onChange={(event) => {
                          void onDisplayLanguageChange(event.target.value);
                        }}
                      >
                        {languageOptions.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label || DISPLAY_LANGUAGE_FALLBACKS[option.value]}
                          </option>
                        ))}
                      </select>
                    </Field>
                  </div>
                ) : null}

                {currentStep === 'provider' ? (
                  <div className="onboarding-form-grid">
                    <Field label={t('onboarding.field.provider_route')}>
                      <select
                        className="onboarding-input"
                        value={selectedProvider}
                        onChange={(event) => setSelectedProvider(event.target.value)}
                        disabled={chatSetupSkipped}
                      >
                        <option value="openai">{t('onboarding.provider.openai')}</option>
                        <option value="custom">{t('onboarding.provider.custom')}</option>
                      </select>
                    </Field>

                    <Field
                      label={t('onboarding.field.api_base_url')}
                      hint={t('onboarding.field.api_base_url_hint')}
                    >
                      <input
                        className="onboarding-input"
                        type="text"
                        value={baseUrl}
                        onChange={(event) => setBaseUrl(event.target.value)}
                        placeholder="https://api.example.com/v1"
                        disabled={chatSetupSkipped}
                      />
                    </Field>

                    <Field label={t('onboarding.field.api_key')}>
                      <input
                        className="onboarding-input"
                        type="password"
                        value={apiKey}
                        onChange={(event) => setApiKey(event.target.value)}
                        placeholder="sk-..."
                        disabled={chatSetupSkipped}
                      />
                    </Field>

                    <Field label={t('onboarding.field.model')}>
                      <input
                        className="onboarding-input"
                        type="text"
                        value={model}
                        onChange={(event) => setModel(event.target.value)}
                        placeholder="gpt-5 / custom-model"
                        disabled={chatSetupSkipped}
                      />
                    </Field>

                    <label className="onboarding-checkbox">
                      <input
                        type="checkbox"
                        checked={launchAtLogin}
                        onChange={(event) => setLaunchAtLogin(event.target.checked)}
                      />
                      <span>{t('onboarding.field.launch_at_login')}</span>
                    </label>
                  </div>
                ) : null}

                {currentStep === 'migration' ? (
                  <div className="onboarding-form-grid">
                    <label className="onboarding-checkbox">
                      <input
                        type="checkbox"
                        checked={importLegacyData}
                        onChange={(event) => setImportLegacyData(event.target.checked)}
                      />
                      <span>{t('onboarding.field.import_legacy')}</span>
                    </label>

                    <div className="onboarding-inline-actions">
                      <button type="button" className="secondary-button" onClick={handlePickLegacyRoot}>
                        {t('onboarding.button.choose_folder')}
                      </button>
                      <span className="onboarding-inline-note">
                        {legacyRoot
                          ? `${t('onboarding.field.selected_folder')}: ${legacyRoot}`
                          : t('onboarding.field.no_folder_selected')}
                      </span>
                    </div>
                  </div>
                ) : null}

                {currentStep === 'complete' ? (
                  <div className="onboarding-form-grid">
                    <div className="onboarding-complete-summary">
                      <strong>{t('onboarding.complete.summary_title')}</strong>
                      <span>
                        {t('onboarding.complete.summary_language')}: {languageOptions.find((option) => option.value === displayLanguage)?.label || DISPLAY_LANGUAGE_FALLBACKS[displayLanguage]}
                      </span>
                      <span>
                        {t('onboarding.complete.summary_chat')}: {chatSetupSkipped ? t('onboarding.complete.summary_chat_skipped') : selectedProvider}
                      </span>
                      <span>
                        {t('onboarding.complete.summary_legacy_import')}: {importLegacyData ? t('onboarding.complete.summary_legacy_yes') : t('onboarding.complete.summary_legacy_no')}
                      </span>
                    </div>
                  </div>
                ) : null}

                {saveError ? <div className="onboarding-error">{saveError}</div> : null}

                <div className="onboarding-actions">
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={handleBack}
                    disabled={stepIndex === 0 || isSaving}
                  >
                    {t('onboarding.button.back')}
                  </button>

                  {currentStep === 'provider' ? (
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={handleSkipChatSetup}
                      disabled={isSaving}
                    >
                      {t('onboarding.button.skip_chat')}
                    </button>
                  ) : null}

                  <button type="button" onClick={() => void handleContinue()} disabled={isSaving}>
                    {currentStep === 'complete'
                      ? t('onboarding.button.finish')
                      : t('onboarding.button.continue')}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

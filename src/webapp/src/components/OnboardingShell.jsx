import { useMemo, useState } from 'react';

const STEP_ORDER = ['welcome', 'provider', 'migration', 'complete'];

const STEP_CONTENT = {
  welcome: {
    eyebrow: 'First Run',
    title: 'Welcome to Vantage',
    description:
      'This setup flow prepares the packaged app experience: user settings, provider configuration, and history import all move out of the source tree.',
    bullets: [
      'Review what the packaged runtime will keep under the user data directory.',
      'Configure the chat provider or explicitly skip it for now.',
      'Import old history from the current repo only once, then keep using the packaged copy.',
    ],
  },
  provider: {
    eyebrow: 'Chat Setup',
    title: 'Connect the chat provider',
    description:
      'These fields are now saved into providers.json and settings.json. Real backend consumption comes later, but the onboarding flow already persists the values.',
    bullets: [
      'Provider Route, API Base URL, API Key, and Model are all stored in user config.',
      'Launch-at-login preference is stored here and applied in the installer step later.',
      'You can still skip chat setup and finish onboarding without blocking the rest of the app.',
    ],
  },
  migration: {
    eyebrow: 'Data Import',
    title: 'Import legacy history into packaged data',
    description:
      'Choose whether to pull the old history folder into the packaged app data directory. The migration is recorded once and the same source will not be imported twice.',
    bullets: [
      'Only history and state files are copied here.',
      'Large photo and screenshot libraries stay where they already live.',
      'If the same legacy source was already imported, this step will reuse the previous migration record.',
    ],
  },
  complete: {
    eyebrow: 'Finish',
    title: 'Write onboarding state and open the app',
    description:
      'The final step saves onboarding_completed, provider settings, and optional migration state. After that the main workspace opens directly on next launch.',
    bullets: [
      'settings.json records onboarding and launch-at-login preference.',
      'providers.json records the provider selection and credentials you entered.',
      'migration-state.json records where old history came from and when it was imported.',
    ],
  },
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
  initialLaunchAtLogin = false,
  initialLegacyRoot = null,
  initialProviderConfigured = false,
  initialMigrationCompleted = false,
  onComplete,
  onPickLegacyRoot,
}) {
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
  const stepContent = STEP_CONTENT[currentStep];

  const stepCards = useMemo(
    () =>
      STEP_ORDER.map((step, index) => ({
        id: step,
        label: `${index + 1}`,
        title: STEP_CONTENT[step].title,
      })),
    [],
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
          importLegacyData,
          legacyRoot,
          skipChatSetup: chatSetupSkipped,
        });
      } catch (error) {
        setSaveError(error?.message || 'Failed to finish onboarding.');
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
    <div className="app-layout">
      <main className="app-container onboarding-page">
        <section className="glass-panel onboarding-shell">
          <div className="onboarding-shell-header">
            <div>
              <div className="onboarding-eyebrow">{stepContent.eyebrow}</div>
              <h1 className="onboarding-title">{stepContent.title}</h1>
              <p className="onboarding-description">{stepContent.description}</p>
            </div>
            <div className="onboarding-progress-chip">
              Step {stepIndex + 1} / {STEP_ORDER.length}
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
                  {stepContent.bullets.map((bullet) => (
                    <li key={bullet}>{bullet}</li>
                  ))}
                </ul>

                {currentStep === 'provider' ? (
                  <div className="onboarding-form-grid">
                    <Field label="Provider Route">
                      <select
                        className="onboarding-input"
                        value={selectedProvider}
                        onChange={(event) => setSelectedProvider(event.target.value)}
                        disabled={chatSetupSkipped}
                      >
                        <option value="openai">OpenAI-compatible</option>
                        <option value="gemini">Gemini-compatible</option>
                        <option value="custom">Custom provider</option>
                      </select>
                    </Field>

                    <Field
                      label="API Base URL"
                      hint="Saved now for onboarding. Real runtime routing will start using it in later steps."
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

                    <Field label="API Key">
                      <input
                        className="onboarding-input"
                        type="password"
                        value={apiKey}
                        onChange={(event) => setApiKey(event.target.value)}
                        placeholder="sk-..."
                        disabled={chatSetupSkipped}
                      />
                    </Field>

                    <Field label="Model">
                      <input
                        className="onboarding-input"
                        type="text"
                        value={model}
                        onChange={(event) => setModel(event.target.value)}
                        placeholder="gpt-5 / gemini-2.5-pro / custom-model"
                        disabled={chatSetupSkipped}
                      />
                    </Field>

                    <label className="onboarding-checkbox">
                      <input
                        type="checkbox"
                        checked={launchAtLogin}
                        onChange={(event) => setLaunchAtLogin(event.target.checked)}
                      />
                      <span>Start Vantage automatically after Windows login</span>
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
                      <span>Import existing history into the packaged app data directory</span>
                    </label>

                    <Field
                      label="Legacy Source Folder"
                      hint="Pick the old source-tree root that contains the history folder."
                    >
                      <div className="onboarding-inline-row">
                        <input
                          className="onboarding-input"
                          type="text"
                          value={legacyRoot}
                          onChange={(event) => setLegacyRoot(event.target.value)}
                          placeholder="C:\\Users\\97012\\gitee\\ai"
                        />
                        <button
                          type="button"
                          className="onboarding-secondary-button"
                          onClick={handlePickLegacyRoot}
                        >
                          Choose Folder
                        </button>
                      </div>
                    </Field>

                    {initialMigrationCompleted ? (
                      <div className="onboarding-placeholder-item">
                        A legacy import has already been recorded. Reusing the same source will not copy again.
                      </div>
                    ) : null}
                  </div>
                ) : null}

                {currentStep === 'complete' ? (
                  <div className="onboarding-form-grid">
                    <div className="onboarding-placeholder-item">
                      Chat setup: {chatSetupSkipped ? 'Skipped for now' : `Will save ${selectedProvider}`}
                    </div>
                    <div className="onboarding-placeholder-item">
                      Launch at login: {launchAtLogin ? 'Enabled in settings.json' : 'Disabled in settings.json'}
                    </div>
                    <div className="onboarding-placeholder-item">
                      Legacy import: {importLegacyData ? (legacyRoot || 'Source pending') : 'Skipped'}
                    </div>
                  </div>
                ) : null}

                {saveError ? <div className="action-plan-warning">{saveError}</div> : null}
              </div>

              <div className="onboarding-actions">
                <button
                  className="onboarding-secondary-button"
                  onClick={handleBack}
                  disabled={stepIndex === 0 || isSaving}
                >
                  Back
                </button>

                {currentStep === 'provider' ? (
                  <button
                    className="onboarding-secondary-button"
                    onClick={handleSkipChatSetup}
                    disabled={isSaving}
                  >
                    Skip Chat Setup
                  </button>
                ) : null}

                <button onClick={() => void handleContinue()} disabled={isSaving}>
                  {currentStep === 'complete' ? (isSaving ? 'Saving...' : 'Finish Setup') : 'Continue'}
                </button>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

export { STEP_ORDER };

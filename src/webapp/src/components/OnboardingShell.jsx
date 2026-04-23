import { useMemo, useState } from 'react';

const STEP_ORDER = ['welcome', 'provider', 'migration', 'complete'];

const STEP_CONTENT = {
  welcome: {
    eyebrow: 'First Run',
    title: 'Welcome to Vantage',
    description:
      'This setup flow will turn the current project into a desktop-style app. In this step we only wire the shell, so nothing is saved yet.',
    bullets: [
      'Check where your app data already lives.',
      'Preview the chat setup path without asking for provider keys yet.',
      'Confirm how old history import will work before the real migration step lands.',
    ],
  },
  provider: {
    eyebrow: 'Chat Setup',
    title: 'Choose how chat setup should feel',
    description:
      'The real provider save flow comes in the next step. Right now this page only reserves the structure for provider selection, API keys, and startup preferences.',
    bullets: [
      'Primary provider selector placeholder',
      'API key and endpoint placeholder',
      'Optional launch-at-login preference preview',
    ],
  },
  migration: {
    eyebrow: 'Data Import',
    title: 'Prepare legacy history import',
    description:
      'The actual copy and dedupe logic is not connected in this step. This page exists so the first-run flow already has a stable place for old history import.',
    bullets: [
      'Auto-detected legacy paths will appear here',
      'Manual folder picker will connect here next',
      'Import summary and conflict handling will be added in the real migration step',
    ],
  },
  complete: {
    eyebrow: 'Preview Ready',
    title: 'Onboarding shell is in place',
    description:
      'You can open the app preview now. The next step will connect these placeholders to real persistence and migration.',
    bullets: [
      'Your workspace tabs stay unchanged behind this shell',
      'This preview does not write onboarding_completed yet',
      'Restarting the app will still reopen onboarding until the real save step is added',
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

export default function OnboardingShell({ initialLaunchAtLogin = false, onOpenAppPreview }) {
  const [stepIndex, setStepIndex] = useState(0);
  const [chatSetupSkipped, setChatSetupSkipped] = useState(false);
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
    setStepIndex((current) => Math.max(current - 1, 0));
  };

  const handleContinue = () => {
    if (currentStep === 'complete') {
      onOpenAppPreview();
      return;
    }
    setStepIndex((current) => Math.min(current + 1, STEP_ORDER.length - 1));
  };

  const handleSkipChatSetup = () => {
    setChatSetupSkipped(true);
    setStepIndex(STEP_ORDER.indexOf('migration'));
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

                <div className="onboarding-placeholder-band">
                  {currentStep === 'provider' ? (
                    <>
                      <div className="onboarding-placeholder-item">
                        Launch at login preview: {initialLaunchAtLogin ? 'On' : 'Off'}
                      </div>
                      <div className="onboarding-placeholder-item">
                        Chat setup status: {chatSetupSkipped ? 'Skipped for this preview' : 'Not configured yet'}
                      </div>
                    </>
                  ) : null}

                  {currentStep === 'migration' ? (
                    <>
                      <div className="onboarding-placeholder-item">Legacy history import target: pending</div>
                      <div className="onboarding-placeholder-item">Manual source picker: pending</div>
                    </>
                  ) : null}

                  {currentStep === 'complete' ? (
                    <div className="onboarding-placeholder-item">
                      Preview mode only. Real onboarding completion will be saved in the next step.
                    </div>
                  ) : null}
                </div>
              </div>

              <div className="onboarding-actions">
                <button
                  className="onboarding-secondary-button"
                  onClick={handleBack}
                  disabled={stepIndex === 0}
                >
                  Back
                </button>

                {currentStep === 'provider' ? (
                  <button className="onboarding-secondary-button" onClick={handleSkipChatSetup}>
                    Skip Chat Setup
                  </button>
                ) : null}

                <button onClick={handleContinue}>
                  {currentStep === 'complete' ? 'Open App Preview' : 'Continue'}
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

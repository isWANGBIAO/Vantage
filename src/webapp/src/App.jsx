import { Suspense, lazy, useEffect, useRef, useState } from 'react';
import { Moon, Sun } from 'lucide-react';
import './App.css';
import ActionPlanContainer from './components/ActionPlanContainer';
import OnboardingShell from './components/OnboardingShell';
import { completeOnboardingSetup, loadOnboardingState, pickLegacyRoot } from './utils/onboardingState';
import {
  DisplayLanguageProvider,
  useDisplayLanguage,
} from './context/DisplayLanguageContext.jsx';

function lazyWithPreload(factory) {
  const Component = lazy(factory);
  Component.preload = factory;
  return Component;
}

const Dashboard = lazyWithPreload(() => import('./components/Dashboard'));
const ProjectProgress = lazyWithPreload(() => import('./components/ProjectProgress'));
const ExpenseSheet = lazyWithPreload(() => import('./components/ExpenseSheet'));
const Plots = lazyWithPreload(() => import('./components/Plots'));
const SystemLogs = lazyWithPreload(() => import('./components/SystemLogs'));
const FaceHistory = lazyWithPreload(() => import('./components/FaceHistory'));

const BACKGROUND_TAB_COMPONENTS = [
  Dashboard,
  ProjectProgress,
  ExpenseSheet,
  Plots,
  SystemLogs,
  FaceHistory,
];

const NAV_ITEMS = [
  { key: 'dashboard', labelKey: 'app.nav.dashboard' },
  { key: 'action plan', labelKey: 'app.nav.action_plan' },
  { key: 'project progress', labelKey: 'app.nav.project_progress' },
  { key: 'expense sheet', labelKey: 'app.nav.expense_sheet' },
  { key: 'plots', labelKey: 'app.nav.plots' },
  { key: 'system logs', labelKey: 'app.nav.system_logs' },
  { key: 'face history', labelKey: 'app.nav.face_history' },
];

function DisplayLanguageSelect() {
  const { displayLanguage, languageOptions, setDisplayLanguage, t } = useDisplayLanguage();

  return (
    <label className="app-language-control">
      <span className="app-language-label">{t('app.language.label')}</span>
      <select
        className="app-language-select"
        value={displayLanguage}
        aria-label={t('app.language.label')}
        onChange={(event) => {
          void setDisplayLanguage(event.target.value);
        }}
      >
        {languageOptions.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function AppShell() {
  const { t, displayLanguage, setDisplayLanguage } = useDisplayLanguage();
  const [activeTab, setActiveTab] = useState('action plan');
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'dark');
  const [backgroundTabsReady, setBackgroundTabsReady] = useState(false);
  const lastAppliedOnboardingLanguageRef = useRef(null);
  const [onboardingState, setOnboardingState] = useState(() => ({
    loading: true,
    completed: true,
    launchAtLogin: false,
    displayLanguage: 'system',
    providerConfigured: false,
    migrationCompleted: false,
    legacyRoot: null,
  }));
  const appLayoutClassName =
    typeof window !== 'undefined' && window.electronAPI
      ? 'app-layout app-layout--electron'
      : 'app-layout';

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('theme', theme);
    void window.electronAPI?.setTitleBarTheme?.(theme);
  }, [theme]);

  useEffect(() => {
    let cancelled = false;

    const initializeOnboardingState = async () => {
      const nextState = await loadOnboardingState();
      if (!cancelled) {
        setOnboardingState({
          loading: false,
          completed: nextState.completed,
          launchAtLogin: nextState.launchAtLogin,
          displayLanguage: nextState.displayLanguage,
          providerConfigured: nextState.providerConfigured,
          migrationCompleted: nextState.migrationCompleted,
          legacyRoot: nextState.legacyRoot,
        });
      }
    };

    void initializeOnboardingState();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    const preloadTabs = async () => {
      await Promise.all(BACKGROUND_TAB_COMPONENTS.map((Component) => Component.preload()));
      if (!cancelled) {
        setBackgroundTabsReady(true);
      }
    };

    void preloadTabs();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (onboardingState.loading || !onboardingState.displayLanguage) {
      return;
    }

    if (lastAppliedOnboardingLanguageRef.current === onboardingState.displayLanguage) {
      return;
    }

    lastAppliedOnboardingLanguageRef.current = onboardingState.displayLanguage;

    if (onboardingState.displayLanguage !== displayLanguage) {
      void setDisplayLanguage(onboardingState.displayLanguage);
    }
  }, [displayLanguage, onboardingState.displayLanguage, onboardingState.loading, setDisplayLanguage]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
  };

  const handleCompleteOnboarding = async (submission) => {
    const result = await completeOnboardingSetup(submission);
    const nextState = await loadOnboardingState();
    setOnboardingState({
      loading: false,
      completed: nextState.completed,
      launchAtLogin: nextState.launchAtLogin,
      displayLanguage: nextState.displayLanguage,
      providerConfigured: nextState.providerConfigured,
      migrationCompleted: nextState.migrationCompleted,
      legacyRoot: nextState.legacyRoot,
    });
    return result;
  };

  const handlePickLegacyRoot = async () => pickLegacyRoot();

  const showOnboardingShell = !onboardingState.loading && !onboardingState.completed;

  if (onboardingState.loading) {
    return (
      <div className={appLayoutClassName}>
        <main className="app-container onboarding-loading-shell">
          <div className="glass-panel onboarding-loading-card">
            <div className="onboarding-eyebrow">{t('app.loading.eyebrow')}</div>
            <h1 className="onboarding-title">{t('app.loading.title')}</h1>
            <p className="onboarding-description">{t('app.loading.description')}</p>
          </div>
        </main>
      </div>
    );
  }

  if (showOnboardingShell) {
    return (
      <OnboardingShell
        displayLanguage={displayLanguage}
        initialLaunchAtLogin={onboardingState.launchAtLogin}
        initialLegacyRoot={onboardingState.legacyRoot}
        initialProviderConfigured={onboardingState.providerConfigured}
        initialMigrationCompleted={onboardingState.migrationCompleted}
        onComplete={handleCompleteOnboarding}
        onDisplayLanguageChange={setDisplayLanguage}
        onPickLegacyRoot={handlePickLegacyRoot}
      />
    );
  }

  return (
    <div className={appLayoutClassName}>
      <header
        className="app-header"
        style={{
          background: theme === 'dark' ? 'rgba(5, 5, 8, 0.9)' : 'rgba(255, 255, 255, 0.95)',
        }}
      >
        <div className="app-brand">
          <div
            style={{
              width: '32px',
              height: '32px',
              background: 'var(--gradient-primary)',
              borderRadius: '8px',
              boxShadow: '0 0 15px rgba(108, 92, 231, 0.5)',
            }}
          />
          <h1 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0, letterSpacing: '0.5px' }}>
            Vantage
          </h1>
        </div>

        <div className="app-header-actions">
          <nav className="app-nav">
            {NAV_ITEMS.map((item) => {
              const isActive = item.key === activeTab;

              return (
                <a
                  key={item.key}
                  href="#"
                  className={`app-nav-link ${isActive ? 'active-nav' : ''}`}
                  style={{
                    color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                    fontWeight: isActive ? 600 : 400,
                  }}
                  onClick={(event) => {
                    event.preventDefault();
                    setActiveTab(item.key);
                  }}
                >
                  {t(item.labelKey)}
                </a>
              );
            })}
          </nav>

          <DisplayLanguageSelect />

          <button
            className="theme-toggle"
            onClick={toggleTheme}
            title={t(theme === 'dark' ? 'app.theme.switch_to_light' : 'app.theme.switch_to_dark')}
          >
            {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          </button>
        </div>
      </header>

      <main className="app-container app-main">
        <Suspense fallback={null}>
          {(activeTab === 'dashboard' || backgroundTabsReady) ? (
            <div style={{ display: activeTab === 'dashboard' ? 'block' : 'none' }}>
              <Dashboard isVisible={activeTab === 'dashboard'} />
            </div>
          ) : null}
        </Suspense>
        <div style={{ display: activeTab === 'action plan' ? 'block' : 'none', height: '100%' }}>
          <ActionPlanContainer isVisible={activeTab === 'action plan'} />
        </div>
        <Suspense fallback={null}>
          {(activeTab === 'project progress' || backgroundTabsReady) ? (
            <div style={{ display: activeTab === 'project progress' ? 'block' : 'none', height: '100%' }}>
              <ProjectProgress />
            </div>
          ) : null}
        </Suspense>
        <Suspense fallback={null}>
          {(activeTab === 'expense sheet' || backgroundTabsReady) ? (
            <div style={{ display: activeTab === 'expense sheet' ? 'block' : 'none' }}>
              <ExpenseSheet theme={theme} />
            </div>
          ) : null}
        </Suspense>
        <Suspense fallback={null}>
          {(activeTab === 'plots' || backgroundTabsReady) ? (
            <div style={{ display: activeTab === 'plots' ? 'block' : 'none' }}>
              <Plots theme={theme} />
            </div>
          ) : null}
        </Suspense>
        <Suspense fallback={null}>
          {(activeTab === 'system logs' || backgroundTabsReady) ? (
            <div style={{ display: activeTab === 'system logs' ? 'block' : 'none' }}>
              <SystemLogs />
            </div>
          ) : null}
        </Suspense>
        <Suspense fallback={null}>
          {(activeTab === 'face history' || backgroundTabsReady) ? (
            <div style={{ display: activeTab === 'face history' ? 'block' : 'none' }}>
              <FaceHistory isVisible={activeTab === 'face history'} />
            </div>
          ) : null}
        </Suspense>
      </main>

      {activeTab !== 'plots' &&
        activeTab !== 'action plan' &&
        activeTab !== 'face history' &&
        activeTab !== 'expense sheet' &&
        activeTab !== 'system logs' &&
        activeTab !== 'project progress' && (
          <footer
            style={{
              padding: '2rem',
              textAlign: 'center',
              color: 'var(--text-muted)',
              fontSize: '0.85rem',
              borderTop: '1px solid var(--border-color)',
              marginTop: 'auto',
            }}
          >
            {t('app.footer.powered_by', { provider: 'Gemini' })}
          </footer>
        )}
    </div>
  );
}

export default function App() {
  return (
    <DisplayLanguageProvider>
      <AppShell />
    </DisplayLanguageProvider>
  );
}

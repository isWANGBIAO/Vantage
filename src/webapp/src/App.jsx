import { Suspense, lazy, useEffect, useState } from 'react';
import './App.css';
import ActionPlanContainer from './components/ActionPlanContainer';
import OnboardingShell from './components/OnboardingShell';
import { Sun, Moon } from 'lucide-react';
import { completeOnboardingSetup, loadOnboardingState, pickLegacyRoot } from './utils/onboardingState';

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
  'Dashboard',
  'Action Plan',
  'Project Progress',
  'Expense Sheet',
  'Plots',
  'System Logs',
  'Face History',
];

function App() {
  const [activeTab, setActiveTab] = useState('action plan');
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'dark');
  const [backgroundTabsReady, setBackgroundTabsReady] = useState(false);
  const [onboardingState, setOnboardingState] = useState(() => ({
    loading: true,
    completed: true,
    launchAtLogin: false,
    providerConfigured: false,
    migrationCompleted: false,
    legacyRoot: null,
  }));

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('theme', theme);
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
      <div className="app-layout">
        <main className="app-container onboarding-loading-shell">
          <div className="glass-panel onboarding-loading-card">
            <div className="onboarding-eyebrow">Preparing Vantage</div>
            <h1 className="onboarding-title">Checking first-run state</h1>
            <p className="onboarding-description">
              Loading the desktop setup contract before opening the workspace.
            </p>
          </div>
        </main>
      </div>
    );
  }

  if (showOnboardingShell) {
    return (
      <OnboardingShell
        initialLaunchAtLogin={onboardingState.launchAtLogin}
        initialLegacyRoot={onboardingState.legacyRoot}
        initialProviderConfigured={onboardingState.providerConfigured}
        initialMigrationCompleted={onboardingState.migrationCompleted}
        onComplete={handleCompleteOnboarding}
        onPickLegacyRoot={handlePickLegacyRoot}
      />
    );
  }

  return (
    <div className="app-layout">
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
              const key = item.toLowerCase();
              const isActive = key === activeTab;

              return (
                <a
                  key={item}
                  href="#"
                  className={`app-nav-link ${isActive ? 'active-nav' : ''}`}
                  style={{
                    color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                    fontWeight: isActive ? 600 : 400,
                  }}
                  onClick={(event) => {
                    event.preventDefault();
                    setActiveTab(key);
                  }}
                >
                  {item}
                </a>
              );
            })}
          </nav>

          <button
            className="theme-toggle"
            onClick={toggleTheme}
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
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
              <FaceHistory />
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
            2026 Vantage | Powered by Gemini
          </footer>
        )}
    </div>
  );
}

export default App;

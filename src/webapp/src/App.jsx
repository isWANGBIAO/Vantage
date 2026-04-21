import { lazy, Suspense, useEffect, useState } from 'react';
import './App.css';
import ActionPlanContainer from './components/ActionPlanContainer';
import { Sun, Moon } from 'lucide-react';

const Dashboard = lazy(() => import('./components/Dashboard'));
const ProjectProgress = lazy(() => import('./components/ProjectProgress'));
const ExpenseSheet = lazy(() => import('./components/ExpenseSheet'));
const Plots = lazy(() => import('./components/Plots'));
const SystemLogs = lazy(() => import('./components/SystemLogs'));
const FaceHistory = lazy(() => import('./components/FaceHistory'));

const DEFAULT_TAB = 'action plan';

const NAV_ITEMS = [
  { label: 'Dashboard', key: 'dashboard', Component: Dashboard },
  { label: 'Action Plan', key: 'action plan', Component: ActionPlanContainer, fullHeight: true },
  { label: 'Project Progress', key: 'project progress', Component: ProjectProgress, fullHeight: true },
  { label: 'Expense Sheet', key: 'expense sheet', Component: ExpenseSheet },
  { label: 'Plots', key: 'plots', Component: Plots },
  { label: 'System Logs', key: 'system logs', Component: SystemLogs },
  { label: 'Face History', key: 'face history', Component: FaceHistory },
];

function App() {
  const [activeTab, setActiveTab] = useState(DEFAULT_TAB);
  const [visitedTabs, setVisitedTabs] = useState(() => new Set([DEFAULT_TAB]));
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'dark');

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('theme', theme);
  }, [theme]);

  useEffect(() => {
    setVisitedTabs((prev) => {
      if (prev.has(activeTab)) {
        return prev;
      }

      const next = new Set(prev);
      next.add(activeTab);
      return next;
    });
  }, [activeTab]);

  useEffect(() => {
    const preloadTabs = () => {
      void import('./components/Dashboard');
      void import('./components/ProjectProgress');
      void import('./components/ExpenseSheet');
      void import('./components/Plots');
      void import('./components/SystemLogs');
      void import('./components/FaceHistory');
    };

    if (window.requestIdleCallback) {
      const idleId = window.requestIdleCallback(preloadTabs);
      return () => window.cancelIdleCallback?.(idleId);
    }

    const timeoutId = window.setTimeout(preloadTabs, 300);
    return () => window.clearTimeout(timeoutId);
  }, []);

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
  };

  const renderTabFallback = (label) => (
    <div
      className="glass-panel"
      style={{
        padding: '1.5rem',
        color: 'var(--text-secondary)',
      }}
    >
      Loading {label}...
    </div>
  );

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
                  {item.label}
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
        {NAV_ITEMS.map((tab) => {
          if (!visitedTabs.has(tab.key)) {
            return null;
          }

          const isVisible = tab.key === activeTab;

          return (
            <div
              key={tab.key}
              style={{
                display: isVisible ? 'block' : 'none',
                height: tab.fullHeight ? '100%' : undefined,
              }}
            >
              <Suspense fallback={isVisible ? renderTabFallback(tab.label) : null}>
                <tab.Component theme={theme} isVisible={isVisible} />
              </Suspense>
            </div>
          );
        })}
      </main>

      {activeTab === 'dashboard' && (
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

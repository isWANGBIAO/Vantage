import { useEffect, useState } from 'react';
import './App.css';
import Dashboard from './components/Dashboard';
import Plots from './components/Plots';
import SystemLogs from './components/SystemLogs';
import ActionPlanContainer from './components/ActionPlanContainer';
import FaceHistory from './components/FaceHistory';
import ExpenseSheet from './components/ExpenseSheet';
import ProjectProgress from './components/ProjectProgress';
import { Sun, Moon } from 'lucide-react';

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

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
  };

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
        <div style={{ display: activeTab === 'dashboard' ? 'block' : 'none' }}>
          <Dashboard />
        </div>
        <div style={{ display: activeTab === 'action plan' ? 'block' : 'none', height: '100%' }}>
          <ActionPlanContainer isVisible={activeTab === 'action plan'} />
        </div>
        <div style={{ display: activeTab === 'project progress' ? 'block' : 'none', height: '100%' }}>
          <ProjectProgress />
        </div>
        <div style={{ display: activeTab === 'expense sheet' ? 'block' : 'none' }}>
          <ExpenseSheet theme={theme} />
        </div>
        <div style={{ display: activeTab === 'plots' ? 'block' : 'none' }}>
          <Plots theme={theme} />
        </div>
        <div style={{ display: activeTab === 'system logs' ? 'block' : 'none' }}>
          <SystemLogs />
        </div>
        <div style={{ display: activeTab === 'face history' ? 'block' : 'none' }}>
          <FaceHistory />
        </div>
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

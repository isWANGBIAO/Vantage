
import { useState, useEffect } from 'react'
import './App.css'
import Dashboard from './components/Dashboard';
import ChatInterface from './components/ChatInterface';
import ActionPlan from './components/ActionPlan';
import Plots from './components/Plots';
import SystemLogs from './components/SystemLogs';
import ActionPlanContainer from './components/ActionPlanContainer';
import FaceHistory from './components/FaceHistory';
import ExpenseSheet from './components/ExpenseSheet';
import ProjectProgress from './components/ProjectProgress';
import { Sun, Moon } from 'lucide-react';

function App() {
  const [activeTab, setActiveTab] = useState('action plan');
  const [theme, setTheme] = useState(() => {
    // Load from localStorage or default to dark
    return localStorage.getItem('theme') || 'dark';
  });

  // Apply theme on mount and change
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => prev === 'dark' ? 'light' : 'dark');
  };

  // Removed renderContent() - now using persistent mount pattern
  // All components stay mounted, visibility controlled by CSS

  return (
    <div className="app-layout">
      <header style={{
        padding: '1rem 2rem',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        borderBottom: '1px solid var(--border-color)',
        background: theme === 'dark' ? 'rgba(5, 5, 8, 0.9)' : 'rgba(255, 255, 255, 0.95)',
        backdropFilter: 'blur(20px)',
        position: 'sticky',
        top: 0,
        zIndex: 100,
        boxShadow: '0 4px 30px rgba(0, 0, 0, 0.5)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <div style={{
            width: '32px',
            height: '32px',
            background: 'var(--gradient-primary)',
            borderRadius: '8px',
            boxShadow: '0 0 15px rgba(108, 92, 231, 0.5)'
          }}></div>
          <h1 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0, letterSpacing: '0.5px' }}>
            Vantage
          </h1>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '2rem' }}>
          <nav style={{ display: 'flex', gap: '2rem' }}>
            {['Dashboard', 'Action Plan', 'Project Progress', 'Expense Sheet', 'Plots', 'System Logs', 'Face History'].map(item => (
              <a
                key={item}
                href="#"
                style={{
                  color: item.toLowerCase() === activeTab ? 'var(--text-primary)' : 'var(--text-secondary)',
                  fontWeight: item.toLowerCase() === activeTab ? 600 : 400,
                  transition: 'all 0.3s ease',
                  fontSize: '0.95rem',
                  textDecoration: 'none',
                  position: 'relative'
                }}
                className={item.toLowerCase() === activeTab ? 'active-nav' : ''}
                onClick={(e) => {
                  e.preventDefault();
                  setActiveTab(item.toLowerCase());
                }}
              >
                {item}
              </a>
            ))}
          </nav>

          {/* Theme Toggle Button */}
          <button
            onClick={toggleTheme}
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-color)',
              borderRadius: '50%',
              width: '36px',
              height: '36px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              color: 'var(--text-secondary)',
              transition: 'all 0.3s ease'
            }}
          >
            {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          </button>
        </div>
      </header>

      <main className="app-container" style={{ padding: '2rem', maxWidth: '1600px', margin: '0 auto', width: '100%' }}>
        {/* Persistent mount pattern - components stay mounted, hidden via CSS */}
        <div style={{ display: activeTab === 'dashboard' ? 'block' : 'none' }}>
          <Dashboard />
        </div>
        <div style={{ display: activeTab === 'action plan' ? 'block' : 'none' }}>
          <ActionPlanContainer />
        </div>
        <div style={{ display: activeTab === 'project progress' ? 'block' : 'none', height: '100%' }}>
          <ProjectProgress />
        </div>
        <div style={{ display: activeTab === 'expense sheet' ? 'block' : 'none' }}>
          <ExpenseSheet />
        </div>
        <div style={{ display: activeTab === 'plots' ? 'block' : 'none' }}>
          <Plots />
        </div>
        <div style={{ display: activeTab === 'system logs' ? 'block' : 'none' }}>
          <SystemLogs />
        </div>
        <div style={{ display: activeTab === 'face history' ? 'block' : 'none' }}>
          <FaceHistory />
        </div>
      </main>

      {activeTab !== 'plots' && activeTab !== 'action plan' && activeTab !== 'face history' && activeTab !== 'expense sheet' && activeTab !== 'project progress' && (
        <footer style={{
          padding: '2rem',
          textAlign: 'center',
          color: 'var(--text-muted)',
          fontSize: '0.85rem',
          borderTop: '1px solid var(--border-color)',
          marginTop: 'auto'
        }}>
          © 2026 Vantage • Powered by Gemini
        </footer>
      )}
    </div>
  )
}

export default App

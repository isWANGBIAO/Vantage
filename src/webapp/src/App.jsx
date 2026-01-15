import { useState } from 'react'
import './App.css'
import Dashboard from './components/Dashboard';
import ChatInterface from './components/ChatInterface';
import ActionPlan from './components/ActionPlan';
import Plots from './components/Plots';
import SystemLogs from './components/SystemLogs';

function App() {
  const [activeTab, setActiveTab] = useState('dashboard');

  const renderContent = () => {
    switch (activeTab) {
      case 'dashboard': return <Dashboard />;
      case 'action plan': return <ActionPlan />;
      case 'plots': return <Plots />;
      case 'system logs': return <SystemLogs />;
      case 'chat': return <ChatInterface />;
      default: return <Dashboard />;
    }
  };

  return (
    <div className="app-layout">
      <header style={{
        padding: '1rem 2rem',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        borderBottom: '1px solid var(--border-color)',
        background: 'rgba(5, 5, 8, 0.9)',
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
            AI <span className="text-gradient">Manager</span>
          </h1>
        </div>
        <nav style={{ display: 'flex', gap: '2rem' }}>
          {['Dashboard', 'Action Plan', 'Plots', 'Chat', 'System Logs'].map(item => (
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
      </header>

      <main className="app-container" style={{ padding: '2rem', maxWidth: '1600px', margin: '0 auto', width: '100%' }}>
        {renderContent()}
      </main>

      <footer style={{
        padding: '2rem',
        textAlign: 'center',
        color: 'var(--text-muted)',
        fontSize: '0.85rem',
        borderTop: '1px solid var(--border-color)',
        marginTop: 'auto'
      }}>
        © 2026 AI Manager Premium Console • Powered by Gemini
      </footer>
    </div>
  )
}

export default App

import { useState } from 'react';
import ActionPlan from './ActionPlan';
import ChatInterface from './ChatInterface';
import { FileText, MessageSquare } from 'lucide-react';

export default function ActionPlanContainer() {
  const [subTab, setSubTab] = useState('plan');

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: 'calc(100vh - 220px)',
        gap: '1rem',
        overflow: 'hidden',
        boxSizing: 'border-box',
      }}
    >
      <div
        className="glass-panel"
        style={{
          padding: '0.5rem',
          display: 'flex',
          gap: '0.5rem',
          width: 'fit-content',
          flexWrap: 'wrap',
        }}
      >
        <button
          onClick={() => setSubTab('plan')}
          style={{
            background: subTab === 'plan' ? 'var(--bg-surface-hover)' : 'transparent',
            color: subTab === 'plan' ? 'var(--text-primary)' : 'var(--text-secondary)',
            boxShadow: 'none',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            padding: '0.5rem 1rem',
            fontSize: '0.9rem',
          }}
        >
          <FileText size={16} />
          Plan
        </button>
        <button
          onClick={() => setSubTab('chat')}
          style={{
            background: subTab === 'chat' ? 'var(--bg-surface-hover)' : 'transparent',
            color: subTab === 'chat' ? 'var(--text-primary)' : 'var(--text-secondary)',
            boxShadow: 'none',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            padding: '0.5rem 1rem',
            fontSize: '0.9rem',
          }}
        >
          <MessageSquare size={16} />
          Chat
        </button>
      </div>

      <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
        <div style={{ height: '100%', display: subTab === 'plan' ? 'block' : 'none' }}>
          <ActionPlan />
        </div>
        <div style={{ height: '100%', display: subTab === 'chat' ? 'block' : 'none' }}>
          <ChatInterface />
        </div>
      </div>
    </div>
  );
}

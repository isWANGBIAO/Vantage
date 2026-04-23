import { useState } from 'react';
import ActionPlan from './ActionPlan';
import ChatInterface from './ChatInterface';
import UsagePanel from './UsagePanel';
import { BarChart3, FileText } from 'lucide-react';
import { useDisplayLanguage } from '../context/DisplayLanguageContext.jsx';

export default function ActionPlanContainer({ isVisible = true }) {
  const { t } = useDisplayLanguage();
  const [subTab, setSubTab] = useState('plan');

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: subTab === 'usage' ? 'calc(100vh - 220px)' : 'auto',
        gap: '1rem',
        overflow: subTab === 'usage' ? 'hidden' : 'visible',
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
          {t('action_plan.tab.plan')}
        </button>
        <button
          onClick={() => setSubTab('usage')}
          style={{
            background: subTab === 'usage' ? 'var(--bg-surface-hover)' : 'transparent',
            color: subTab === 'usage' ? 'var(--text-primary)' : 'var(--text-secondary)',
            boxShadow: 'none',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            padding: '0.5rem 1rem',
            fontSize: '0.9rem',
          }}
        >
          <BarChart3 size={16} />
          {t('action_plan.tab.usage')}
        </button>
      </div>

      <div style={{ flex: subTab === 'usage' ? 1 : '0 0 auto', minHeight: 0, position: 'relative' }}>
        <div style={{ display: subTab === 'plan' ? 'block' : 'none' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <ActionPlan isVisible={isVisible && subTab === 'plan'} layoutMode="stacked" />
            <ChatInterface embedded />
          </div>
        </div>
        <div style={{ height: '100%', display: subTab === 'usage' ? 'block' : 'none' }}>
          <UsagePanel />
        </div>
      </div>
    </div>
  );
}

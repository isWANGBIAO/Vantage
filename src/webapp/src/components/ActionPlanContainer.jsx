import { useState } from 'react';
import ActionPlan from './ActionPlan';
import ChatInterface from './ChatInterface';
import { FileText, MessageSquare } from 'lucide-react';

export default function ActionPlanContainer() {
    const [subTab, setSubTab] = useState('plan'); // 'plan' or 'chat'

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: '1rem' }}>
            {/* Sub-Tabs - Similar to PyQt's sub_tab_widget */}
            <div className="glass-panel" style={{
                padding: '0.5rem',
                display: 'flex',
                gap: '0.5rem',
                width: 'fit-content'
            }}>
                <button
                    onClick={() => setSubTab('plan')}
                    style={{
                        background: subTab === 'plan' ? 'var(--bg-surface-hover)' : 'transparent',
                        color: subTab === 'plan' ? 'var(--text-primary)' : 'var(--text-secondary)',
                        boxShadow: 'none',
                        display: 'flex', alignItems: 'center', gap: '0.5rem',
                        padding: '0.5rem 1rem',
                        fontSize: '0.9rem'
                    }}
                >
                    <FileText size={16} />
                    📋 计划详情 (Plan)
                </button>
                <button
                    onClick={() => setSubTab('chat')}
                    style={{
                        background: subTab === 'chat' ? 'var(--bg-surface-hover)' : 'transparent',
                        color: subTab === 'chat' ? 'var(--text-primary)' : 'var(--text-secondary)',
                        boxShadow: 'none',
                        display: 'flex', alignItems: 'center', gap: '0.5rem',
                        padding: '0.5rem 1rem',
                        fontSize: '0.9rem'
                    }}
                >
                    <MessageSquare size={16} />
                    💬 对话 (Chat)
                </button>
            </div>

            {/* Content Area */}
            <div style={{ flex: 1, minHeight: 0 }}>
                {subTab === 'plan' ? <ActionPlan /> : <ChatInterface />}
            </div>
        </div>
    );
}

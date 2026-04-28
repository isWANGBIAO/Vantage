import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchBackendJson } from '../utils/backendRequest';
import { detectSystemLogSeverity, resolveSystemLogColor } from './systemLogSeverity.js';
import { useDisplayLanguage } from '../context/DisplayLanguageContext.jsx';

function maskSensitiveLogLine(logLine) {
    return String(logLine || '')
        .replace(/[A-Z]:\\[^\s"'<>]+/g, '[local-path]')
        .replace(/\b(?:lat|latitude|lon|longitude)=?-?\d+(?:\.\d+)?/gi, '[coordinate]')
        .replace(/\b-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}\b/g, '[coordinate]');
}

export default function SystemLogs({ isVisible = false }) {
    const { t } = useDisplayLanguage();
    const [logs, setLogs] = useState([]);
    const [paused, setPaused] = useState(false);
    const [searchTerm, setSearchTerm] = useState('');
    const [severityFilter, setSeverityFilter] = useState('all');
    const [statusMessage, setStatusMessage] = useState('');
    const logEndRef = useRef(null);
    const logScrollerRef = useRef(null);

    useEffect(() => {
        if (!isVisible) {
            return undefined;
        }
        if (paused) {
            return undefined;
        }

        const fetchLogs = async () => {
            try {
                const data = await fetchBackendJson('/api/system_logs', { retryPolicy: 'poll' });
                if (data.logs && Array.isArray(data.logs)) {
                    setLogs(data.logs);
                }
            } catch (e) {
                console.error("Log fetch error:", e);
            }
        };

        fetchLogs();
        const interval = setInterval(fetchLogs, 2000);

        return () => clearInterval(interval);
    }, [isVisible, paused]);

    const visibleLogs = useMemo(() => {
        const normalizedSearch = searchTerm.trim().toLowerCase();
        return logs
            .map((log, index) => ({
                id: `${index}-${log}`,
                original: log,
                text: maskSensitiveLogLine(log),
                severity: detectSystemLogSeverity(log),
                index,
            }))
            .filter((entry) => severityFilter === 'all' || entry.severity === severityFilter)
            .filter((entry) => !normalizedSearch || entry.text.toLowerCase().includes(normalizedSearch));
    }, [logs, searchTerm, severityFilter]);

    useEffect(() => {
        if (!paused && logScrollerRef.current) {
            logEndRef.current?.scrollIntoView({ behavior: 'auto' });
        }
    }, [paused, visibleLogs]);

    const copyVisibleLogs = async () => {
        const payload = visibleLogs.map((entry) => entry.text).join('\n');
        if (!payload) {
            return;
        }
        if (!navigator.clipboard?.writeText) {
            setStatusMessage(t('system_logs.copy_failed'));
            return;
        }
        try {
            await navigator.clipboard.writeText(payload);
            setStatusMessage(t('system_logs.copied'));
        } catch {
            setStatusMessage(t('system_logs.copy_failed'));
        }
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', minHeight: 0 }}>
            <div className="glass-panel" style={{ padding: '1.25rem' }}>
                <h2 style={{ margin: 0 }}>{t('system_logs.title')}</h2>
                <p style={{ margin: 0, color: 'var(--text-secondary)' }}>{t('system_logs.subtitle')}</p>
            </div>

            <div
                className="glass-panel"
                style={{
                    padding: '0.85rem',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.75rem',
                    flexWrap: 'wrap',
                }}
            >
                <button type="button" className="secondary-button" onClick={() => setPaused((value) => !value)}>
                    {paused ? t('system_logs.resume') : t('system_logs.pause')}
                </button>
                <input
                    value={searchTerm}
                    onChange={(event) => setSearchTerm(event.target.value)}
                    placeholder={t('system_logs.search_placeholder')}
                    style={{
                        flex: '1 1 220px',
                        minWidth: 0,
                        border: '1px solid var(--border-color)',
                        borderRadius: 8,
                        background: 'var(--bg-surface)',
                        color: 'var(--text-primary)',
                        padding: '0.55rem 0.75rem',
                    }}
                />
                <select
                    value={severityFilter}
                    onChange={(event) => setSeverityFilter(event.target.value)}
                    style={{
                        border: '1px solid var(--border-color)',
                        borderRadius: 8,
                        background: 'var(--bg-surface)',
                        color: 'var(--text-primary)',
                        padding: '0.55rem 0.75rem',
                    }}
                >
                    <option value="all">{t('system_logs.filter.all')}</option>
                    <option value="error">{t('system_logs.filter.error')}</option>
                    <option value="warning">{t('system_logs.filter.warning')}</option>
                    <option value="info">{t('system_logs.filter.info')}</option>
                </select>
                <button type="button" className="secondary-button" onClick={copyVisibleLogs}>
                    {t('system_logs.copy_visible')}
                </button>
                {statusMessage ? <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>{statusMessage}</span> : null}
            </div>

            <div
                ref={logScrollerRef}
                className="glass-panel"
                style={{
                    minHeight: '360px',
                    maxHeight: 'calc(100vh - 250px)',
                    padding: '1rem',
                    background: 'var(--bg-surface)',
                    fontFamily: 'Consolas, monospace',
                    fontSize: '0.86rem',
                    overflow: 'auto',
                }}
            >
                {visibleLogs.length === 0 ? (
                    <div style={{ color: 'var(--text-muted)', padding: '1rem' }}>{t('system_logs.empty')}</div>
                ) : visibleLogs.map((entry) => (
                    <div
                        key={entry.id}
                        style={{
                            padding: '4px 0',
                            color: resolveSystemLogColor(entry.original),
                            borderBottom: '1px solid var(--border-color)',
                            whiteSpace: 'pre-wrap',
                            overflowWrap: 'anywhere',
                        }}
                    >
                        <span style={{ color: 'var(--text-muted)', marginRight: '10px' }}>{entry.index + 1}</span>
                        {entry.text}
                    </div>
                ))}
                <div ref={logEndRef} />
            </div>
        </div>
    );
}

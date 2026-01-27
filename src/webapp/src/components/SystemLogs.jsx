import { useState, useEffect, useRef } from 'react';

export default function SystemLogs() {
    const [logs, setLogs] = useState([]);
    const logEndRef = useRef(null);

    // In a real scenario, we might use WebSockets or SSE for real-time logs.
    // For now, let's simulate or provide a placeholder.
    useEffect(() => {
        const fetchLogs = async () => {
            try {
                const res = await fetch('/api/system_logs');
                if (res.ok) {
                    const data = await res.json();
                    if (data.logs && Array.isArray(data.logs)) {
                        setLogs(data.logs);
                    }
                }
            } catch (e) {
                console.error("Log fetch error:", e);
            }
        };

        // Initial fetch
        fetchLogs();

        // Poll every 2 seconds
        const interval = setInterval(fetchLogs, 2000);

        return () => clearInterval(interval);
    }, []);

    useEffect(() => {
        logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [logs]);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', height: 'calc(100vh - 160px)' }}>
            <div className="glass-panel" style={{ padding: '1.5rem' }}>
                <h2 style={{ margin: 0 }}>System Monitor Logs</h2>
                <p style={{ margin: 0, color: 'var(--text-secondary)' }}>Real-time backend event stream</p>
            </div>

            <div className="glass-panel" style={{
                flex: 1,
                padding: '1.5rem',
                background: '#050508',
                fontFamily: 'monospace',
                fontSize: '0.9rem',
                overflowY: 'auto'
            }}>
                {logs.map((log, i) => (
                    <div key={i} style={{
                        padding: '4px 0',
                        color: log.includes('Error') ? '#ff7675' : '#55efc4',
                        borderBottom: '1px solid rgba(255,255,255,0.03)'
                    }}>
                        <span style={{ color: '#636e72', marginRight: '10px' }}>{i + 1}</span>
                        {log}
                    </div>
                ))}
                <div ref={logEndRef} />
            </div>
        </div>
    );
}

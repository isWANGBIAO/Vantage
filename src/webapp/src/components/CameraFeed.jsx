import { useState, useEffect } from 'react';

export default function CameraFeed() {
    const [status, setStatus] = useState({ online: false });

    useEffect(() => {
        const checkStatus = async () => {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                setStatus({ online: data.camera_online });
            } catch (err) {
                console.error("Failed to fetch camera status", err);
                setStatus({ online: false });
            }
        };

        checkStatus();
        const interval = setInterval(checkStatus, 5000);
        return () => clearInterval(interval);
    }, []);

    return (
        <div className="glass-panel" style={{ padding: '1rem', height: '100%', display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1rem' }}>
                <h3 style={{ margin: 0 }}>Camera Feed</h3>
                <span style={{
                    color: status.online ? 'var(--accent-color)' : 'var(--text-muted)',
                    display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.9rem'
                }}>
                    <span style={{
                        width: '8px', height: '8px', borderRadius: '50%',
                        background: status.online ? 'var(--accent-color)' : 'var(--text-muted)'
                    }}></span>
                    {status.online ? 'LIVE' : 'OFFLINE'}
                </span>
            </div>

            <div style={{
                flex: 1,
                background: '#000',
                borderRadius: '8px',
                overflow: 'hidden',
                position: 'relative',
                minHeight: '240px'
            }}>
                {status.online ? (
                    <img
                        src="/api/stream"
                        alt="Live Stream"
                        style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                    />
                ) : (
                    <div style={{
                        position: 'absolute', inset: 0,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        color: 'var(--text-muted)'
                    }}>
                        Camera Disconnected
                    </div>
                )}
            </div>
        </div>
    );
}

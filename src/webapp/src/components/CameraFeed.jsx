import { useState, useEffect } from 'react';

export default function CameraFeed() {
    const [status, setStatus] = useState({ online: false });

    useEffect(() => {
        const checkStatus = async () => {
            try {
                const res = await fetch('http://localhost:8000/api/status');
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
        <div style={{
            width: '100%',
            height: '100%',
            background: '#000',
            position: 'relative',
            overflow: 'hidden',
            borderRadius: '8px'
        }}>
            {status.online ? (
                <img
                    src="http://localhost:8000/api/stream"
                    alt="Live Stream"
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                />
            ) : (
                <div style={{
                    width: '100%', height: '100%',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: 'var(--text-muted)'
                }}>
                    Camera Disconnected
                </div>
            )}

            {/* Status Indicator Overlay */}
            <div style={{
                position: 'absolute',
                top: '10px',
                right: '10px',
                background: 'rgba(0,0,0,0.6)',
                padding: '4px 8px',
                borderRadius: '4px',
                display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem',
                color: status.online ? 'var(--accent-color)' : '#999',
                zIndex: 20
            }}>
                <span style={{
                    width: '6px', height: '6px', borderRadius: '50%',
                    background: status.online ? 'var(--accent-color)' : '#999',
                    boxShadow: status.online ? '0 0 8px var(--accent-color)' : 'none'
                }}></span>
                {status.online ? 'LIVE' : 'OFFLINE'}
            </div>
        </div>
    );
}

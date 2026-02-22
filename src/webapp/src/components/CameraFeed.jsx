import { useState, useEffect } from 'react';

export default function CameraFeed() {
    const [status, setStatus] = useState({ online: false, show_person_box: true });
    const [toggling, setToggling] = useState(false);

    useEffect(() => {
        const checkStatus = async () => {
            try {
                const res = await fetch('http://localhost:8000/api/status');
                const data = await res.json();
                setStatus({ online: data.camera_online, show_person_box: data.show_person_box });
            } catch (err) {
                console.error("Failed to fetch camera status", err);
                setStatus(prev => ({ ...prev, online: false }));
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

            {/* Toggle Detection Overlay Button */}
            {status.online && (
                <button
                    onClick={async () => {
                        setToggling(true);
                        try {
                            const res = await fetch('http://localhost:8000/api/toggle_detection', { method: 'POST' });
                            const data = await res.json();
                            setStatus(prev => ({ ...prev, show_person_box: data.show_person_box }));
                        } catch (err) {
                            console.error("Toggle error", err);
                        }
                        setToggling(false);
                    }}
                    disabled={toggling}
                    style={{
                        position: 'absolute',
                        top: '10px',
                        left: '10px', // Place it on the opposite side of the LIVE indicator
                        background: status.show_person_box ? 'rgba(0, 210, 211, 0.2)' : 'rgba(0,0,0,0.6)',
                        border: `1px solid ${status.show_person_box ? 'var(--accent-color)' : 'rgba(255,255,255,0.2)'}`,
                        padding: '4px 8px',
                        borderRadius: '4px',
                        display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem',
                        color: status.show_person_box ? 'var(--accent-color)' : '#999',
                        zIndex: 20,
                        cursor: toggling ? 'wait' : 'pointer',
                        transition: 'all 0.2s',
                        backdropFilter: 'blur(4px)'
                    }}
                    title={status.show_person_box ? "Disable Person Detection" : "Enable Person Detection"}
                >
                    <span style={{
                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center'
                    }}>
                        {status.show_person_box ? '👁️ DETECTING' : '👁️‍🗨️ OFF'}
                    </span>
                </button>
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

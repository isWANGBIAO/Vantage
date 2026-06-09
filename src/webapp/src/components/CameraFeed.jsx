import { useState, useEffect, useRef } from 'react';
import { buildBackendUrl, fetchBackendJson } from '../utils/backendRequest';
import { useDisplayLanguage } from '../context/DisplayLanguageContext.jsx';

export default function CameraFeed({ isVisible = false, privacyRevealed = false }) {
    const { t } = useDisplayLanguage();
    const [status, setStatus] = useState({
        online: false,
        show_person_box: true,
        camera_frame_dark: false,
    });
    const [toggling, setToggling] = useState(false);
    const statusErrorLoggedRef = useRef(false);

    useEffect(() => {
        if (!isVisible) {
            return undefined;
        }

        const checkStatus = async () => {
            try {
                const data = await fetchBackendJson('/api/status', { retryPolicy: 'poll' });
                setStatus({
                    online: data.camera_online,
                    show_person_box: data.show_person_box,
                    camera_frame_dark: Boolean(data.camera_frame_dark),
                });
            } catch (err) {
                if (!statusErrorLoggedRef.current) {
                    statusErrorLoggedRef.current = true;
                    console.error("Failed to fetch camera status", err);
                }
                setStatus(prev => ({ ...prev, online: false }));
            }
        };

        checkStatus();
        const interval = setInterval(checkStatus, 5000);
        return () => clearInterval(interval);
    }, [isVisible]);

    return (
        <div style={{
            width: '100%',
            height: '100%',
            background: '#000',
            position: 'relative',
            overflow: 'hidden',
            borderRadius: '8px'
        }}>
            {status.online && isVisible && privacyRevealed ? (
                <img
                    src={buildBackendUrl('/api/stream')}
                    alt={t('camera_feed.live_stream_alt')}
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                />
            ) : (
                <div style={{
                    width: '100%', height: '100%',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: 'var(--text-muted)'
                }}>
                    {status.online && isVisible && !privacyRevealed
                        ? t('camera_feed.show_stream')
                        : (status.online ? t('camera_feed.ready') : t('camera_feed.disconnected'))}
                </div>
            )}

            {status.online && isVisible && privacyRevealed && status.camera_frame_dark && (
                <div style={{
                    position: 'absolute',
                    left: '50%',
                    top: '50%',
                    transform: 'translate(-50%, -50%)',
                    padding: '0.45rem 0.7rem',
                    borderRadius: '4px',
                    border: '1px solid rgba(255,255,255,0.16)',
                    background: 'rgba(0,0,0,0.68)',
                    color: 'var(--text-secondary)',
                    fontSize: '0.78rem',
                    zIndex: 15,
                    pointerEvents: 'none',
                }}>
                    {t('camera_feed.dark_frame')}
                </div>
            )}

            {/* Toggle Detection Overlay Button */}
            {status.online && isVisible && privacyRevealed && (
                <button
                    onClick={async () => {
                        setToggling(true);
                        try {
                            const data = await fetchBackendJson('/api/toggle_detection', {
                                method: 'POST',
                                retryPolicy: 'mutation',
                            });
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
                        display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.72rem',
                        color: status.show_person_box ? 'var(--accent-color)' : '#999',
                        zIndex: 20,
                        cursor: toggling ? 'wait' : 'pointer',
                        transition: 'all 0.2s',
                        backdropFilter: 'blur(4px)'
                    }}
                    title={status.show_person_box ? t('camera_feed.disable_detection') : t('camera_feed.enable_detection')}
                >
                    <span style={{
                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center'
                    }}>
                        {status.show_person_box ? t('camera_feed.detecting') : t('camera_feed.detection_off')}
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
                display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.72rem',
                color: status.online ? 'var(--accent-color)' : '#999',
                zIndex: 20
            }}>
                <span style={{
                    width: '6px', height: '6px', borderRadius: '50%',
                    background: status.online ? 'var(--accent-color)' : '#999',
                    boxShadow: status.online ? '0 0 8px var(--accent-color)' : 'none'
                }}></span>
                {status.online ? (isVisible && privacyRevealed ? t('camera_feed.live') : t('camera_feed.ready_short')) : t('camera_feed.offline')}
            </div>
        </div>
    );
}

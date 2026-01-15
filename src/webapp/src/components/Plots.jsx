import { useState, useEffect } from 'react';

export default function Plots() {
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [plotUrl, setPlotUrl] = useState(`/static/plots/plot_collage.png?t=${Date.now()}`);

    const refreshPlots = async () => {
        setIsRefreshing(true);
        try {
            const res = await fetch('/api/plots/refresh', { method: 'POST' });
            if (res.ok) {
                // Wait a bit for the script to finish (though it's background, maybe check status if we had one)
                // For now, let's just wait 5 seconds then reload
                setTimeout(() => {
                    setPlotUrl(`/static/plots/plot_collage.png?t=${Date.now()}`);
                    setIsRefreshing(false);
                }, 5000);
            }
        } catch (err) {
            console.error("Failed to refresh plots", err);
            setIsRefreshing(false);
        }
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            <div className="glass-panel" style={{ padding: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h2 style={{ margin: 0 }}>Visual Analysis</h2>
                    <p style={{ margin: 0, color: 'var(--text-secondary)' }}>Data visualization and performance metrics</p>
                </div>
                <button
                    onClick={refreshPlots}
                    disabled={isRefreshing}
                    style={{ padding: '0.8rem 2rem', fontSize: '1rem' }}
                >
                    {isRefreshing ? '⏳ Refreshing...' : '🔄 Refresh Plots'}
                </button>
            </div>

            <div className="glass-panel" style={{
                padding: '1.5rem',
                minHeight: '600px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: '#000'
            }}>
                <img
                    src={plotUrl}
                    alt="Merged Plot Collage"
                    onError={(e) => {
                        e.target.onerror = null;
                        e.target.style.display = 'none';
                    }}
                    style={{
                        maxWidth: '100%',
                        maxHeight: '80vh',
                        objectFit: 'contain',
                        boxShadow: '0 0 40px rgba(0,0,0,0.5)'
                    }}
                />
                {!plotUrl && <div style={{ color: 'var(--text-muted)' }}>No plots found. Click refresh to generate.</div>}
            </div>
        </div>
    );
}

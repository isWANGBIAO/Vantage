import { useState, useEffect, useCallback } from 'react';
import { ChevronLeft, ChevronRight, RefreshCw, Image as ImageIcon } from 'lucide-react';
import { buildBackendUrl, fetchBackend, fetchBackendJson } from '../utils/backendRequest';

export default function Plots() {
    const [plots, setPlots] = useState([]);
    const [currentIndex, setCurrentIndex] = useState(0);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [isLoading, setIsLoading] = useState(true);
    const [imageVersion, setImageVersion] = useState(0);
    const currentPlot = plots[currentIndex];

    const fetchPlots = useCallback(async () => {
        setIsLoading(true);
        try {
            const data = await fetchBackendJson('/api/plots/list', { retryPolicy: 'load' });
            if (data.plots && data.plots.length > 0) {
                // Fix URLs for production
                data.plots.forEach(p => {
                    if (p.url && p.url.startsWith('/')) p.url = buildBackendUrl(p.url);
                });
                setPlots(data.plots);
                setCurrentIndex(0);
                setImageVersion(prev => prev + 1);
            }
        } catch (err) {
            console.error('Failed to fetch plots:', err);
        }
        setIsLoading(false);
    }, []);

    // Fetch plot list on mount
    useEffect(() => {
        const bootstrapTimer = setTimeout(() => {
            void fetchPlots();
        }, 0);

        return () => clearTimeout(bootstrapTimer);
    }, [fetchPlots]);

    const refreshPlots = async () => {
        setIsRefreshing(true);
        try {
            await fetchBackend('/api/plots/refresh', {
                method: 'POST',
                retryPolicy: 'mutation',
            });
            setTimeout(() => {
                fetchPlots();
                setIsRefreshing(false);
            }, 5000);
        } catch (err) {
            console.error('Failed to refresh plots:', err);
            setIsRefreshing(false);
        }
    };

    const goToPrev = useCallback(() => {
        setCurrentIndex(prev => (prev > 0 ? prev - 1 : plots.length - 1));
    }, [plots.length]);

    const goToNext = useCallback(() => {
        setCurrentIndex(prev => (prev < plots.length - 1 ? prev + 1 : 0));
    }, [plots.length]);

    // Keyboard navigation
    useEffect(() => {
        const handleKeyDown = (e) => {
            if (e.key === 'ArrowLeft') goToPrev();
            if (e.key === 'ArrowRight') goToNext();
        };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [goToPrev, goToNext]);

    // Mouse wheel navigation
    const handleWheel = (e) => {
        if (e.deltaY < 0) goToPrev();
        else if (e.deltaY > 0) goToNext();
    };
    const currentPlotSrc = currentPlot?.url ? `${currentPlot.url}?v=${imageVersion}` : '';

    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '1rem',
            height: 'calc(100vh - 220px)',
            overflow: 'hidden',
            boxSizing: 'border-box'
        }}>
            {/* Header */}
            <div className="glass-panel" style={{ padding: '1rem 1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
                <div>
                    <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '1.25rem' }}>
                        <ImageIcon size={20} color="var(--primary-color)" />
                        Visual Analysis
                    </h2>
                    <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                        Data visualization
                        {plots.length > 0 && <span style={{ marginLeft: '1rem' }}>📊 {currentIndex + 1} / {plots.length}</span>}
                    </p>
                </div>

                {/* Center Title */}
                <div style={{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
                    <h3 style={{ margin: 0, fontSize: '1.2rem', color: 'var(--text-primary)', fontWeight: 600, textTransform: 'capitalize' }}>
                        {currentPlot?.name?.replace('.png', '').replace(/_/g, ' ') || ''}
                    </h3>
                </div>

                <button
                    onClick={refreshPlots}
                    disabled={isRefreshing}
                    style={{
                        padding: '0.6rem 1.2rem',
                        fontSize: '0.9rem',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.5rem',
                        background: 'var(--primary-color)',
                        color: '#fff',
                        border: 'none',
                        borderRadius: '8px',
                        cursor: isRefreshing ? 'wait' : 'pointer'
                    }}
                >
                    <RefreshCw size={16} className={isRefreshing ? 'spinning' : ''} />
                    {isRefreshing ? 'Refreshing...' : 'Refresh Plots'}
                </button>
            </div>

            {/* Main Display */}
            <div
                className="glass-panel"
                style={{
                    flex: 1,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    position: 'relative',
                    overflow: 'hidden',
                    minHeight: 0,
                    padding: '0', // Removed padding to maximize space
                    background: 'rgba(0,0,0,0.2)' // Darker background for better contrast
                }}
                onWheel={handleWheel}
            >
                {isLoading ? (
                    <div style={{ color: 'var(--text-muted)' }}>⏳ Loading plots...</div>
                ) : plots.length === 0 ? (
                    <div style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                        <p>📊 No plots found</p>
                        <p style={{ fontSize: '0.9rem' }}>Click "Refresh Plots" to generate</p>
                    </div>
                ) : (
                    <>
                        {/* Left Arrow */}
                        <button
                            onClick={goToPrev}
                            style={{
                                position: 'absolute',
                                left: '0.5rem', // Closer to edge
                                background: 'rgba(0,0,0,0.3)',
                                border: 'none',
                                borderRadius: '50%',
                                width: '40px',
                                height: '40px',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                cursor: 'pointer',
                                color: '#fff',
                                zIndex: 10,
                                transition: 'all 0.2s',
                                backdropFilter: 'blur(4px)'
                            }}
                        >
                            <ChevronLeft size={24} />
                        </button>

                        {/* Image */}
                        <img
                            src={currentPlotSrc}
                            alt={currentPlot.name}
                            style={{
                                maxWidth: '100%',
                                maxHeight: '100%',
                                width: '100%', // Force fill width if aspect ratio allows
                                height: '100%', // Force fill height if aspect ratio allows
                                objectFit: 'contain', // Ensure 16:9 is preserved without cropping
                                borderRadius: '0'
                            }}
                        />

                        {/* Right Arrow */}
                        <button
                            onClick={goToNext}
                            style={{
                                position: 'absolute',
                                right: '1rem',
                                background: 'rgba(0,0,0,0.5)',
                                border: 'none',
                                borderRadius: '50%',
                                width: '48px',
                                height: '48px',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                cursor: 'pointer',
                                color: '#fff',
                                zIndex: 10,
                                transition: 'all 0.2s'
                            }}
                        >
                            <ChevronRight size={28} />
                        </button>
                    </>
                )}
            </div>


        </div>
    );
}

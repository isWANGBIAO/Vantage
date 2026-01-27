import { useState, useEffect, useCallback } from 'react';
import { ChevronLeft, ChevronRight, RefreshCw, Image as ImageIcon } from 'lucide-react';

export default function Plots() {
    const [plots, setPlots] = useState([]);
    const [currentIndex, setCurrentIndex] = useState(0);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [isLoading, setIsLoading] = useState(true);

    // Fetch plot list on mount
    useEffect(() => {
        fetchPlots();
    }, []);

    const fetchPlots = async () => {
        setIsLoading(true);
        try {
            const res = await fetch('/api/plots/list');
            const data = await res.json();
            if (data.plots && data.plots.length > 0) {
                setPlots(data.plots);
                setCurrentIndex(0);
            }
        } catch (err) {
            console.error('Failed to fetch plots:', err);
        }
        setIsLoading(false);
    };

    const refreshPlots = async () => {
        setIsRefreshing(true);
        try {
            const res = await fetch('/api/plots/refresh', { method: 'POST' });
            if (res.ok) {
                // Wait for plots to be generated, then reload
                setTimeout(() => {
                    fetchPlots();
                    setIsRefreshing(false);
                }, 5000);
            }
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

    const currentPlot = plots[currentIndex];

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', height: '80vh' }}>
            {/* Header */}
            <div className="glass-panel" style={{ padding: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <ImageIcon size={24} color="var(--primary-color)" />
                        Visual Analysis
                    </h2>
                    <p style={{ margin: 0, color: 'var(--text-secondary)' }}>
                        Data visualization and performance metrics
                        {plots.length > 0 && <span style={{ marginLeft: '1rem' }}>📊 {currentIndex + 1} / {plots.length}</span>}
                    </p>
                </div>
                <button
                    onClick={refreshPlots}
                    disabled={isRefreshing}
                    style={{
                        padding: '0.8rem 1.5rem',
                        fontSize: '1rem',
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
                    <RefreshCw size={18} className={isRefreshing ? 'spinning' : ''} />
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
                    minHeight: 0
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
                                left: '1rem',
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
                            <ChevronLeft size={28} />
                        </button>

                        {/* Image */}
                        <img
                            src={`${currentPlot.url}?t=${Date.now()}`}
                            alt={currentPlot.name}
                            style={{
                                maxWidth: '90%',
                                maxHeight: '100%',
                                objectFit: 'contain',
                                borderRadius: '8px',
                                boxShadow: '0 0 40px rgba(0,0,0,0.5)'
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

            {/* Thumbnail Strip + Info */}
            {plots.length > 0 && (
                <div className="glass-panel" style={{ padding: '1rem' }}>
                    <div style={{ textAlign: 'center', marginBottom: '0.5rem' }}>
                        <span style={{
                            fontSize: '0.9rem',
                            fontWeight: 600,
                            color: 'var(--text-primary)'
                        }}>
                            {currentPlot?.name?.replace('.png', '').replace(/_/g, ' ')}
                        </span>
                    </div>
                    <div style={{
                        display: 'flex',
                        gap: '0.5rem',
                        overflowX: 'auto',
                        justifyContent: 'center',
                        padding: '0.5rem'
                    }}>
                        {plots.map((plot, i) => (
                            <div
                                key={plot.name}
                                onClick={() => setCurrentIndex(i)}
                                style={{
                                    width: '60px',
                                    height: '40px',
                                    borderRadius: '4px',
                                    overflow: 'hidden',
                                    cursor: 'pointer',
                                    border: i === currentIndex ? '2px solid var(--primary-color)' : '2px solid transparent',
                                    opacity: i === currentIndex ? 1 : 0.5,
                                    transition: 'all 0.2s',
                                    flexShrink: 0
                                }}
                            >
                                <img
                                    src={plot.url}
                                    alt={plot.name}
                                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                                />
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

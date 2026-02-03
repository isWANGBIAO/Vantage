
import React, { useState, useEffect } from 'react';

const FaceHistory = () => {
    const [loading, setLoading] = useState(false);
    const [progress, setProgress] = useState({ percent: 0, status: 'idle', current_file: '' });
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);

    const fetchReport = async () => {
        try {
            const res = await fetch('http://localhost:8000/api/face/report');
            const json = await res.json();
            if (json.error) {
                // Don't set error immediately if just no report, maybe clean state
                if (json.error === "No report generated") return;
                setError(json.error);
            } else {
                setData(json);
                setError(null);
            }
        } catch (err) {
            setError(err.message);
        }
    };

    // Polling for progress
    useEffect(() => {
        let interval;
        if (loading) {
            interval = setInterval(async () => {
                try {
                    const res = await fetch('http://localhost:8000/api/face/progress');
                    if (res.ok) {
                        const p = await res.json();
                        setProgress(p);
                        if (p.percent >= 100 || (p.status === 'idle' && p.percent === 0)) {
                            // Analysis likely done or failed/stale
                            // But we can't be sure if it's "starting" (0%) or "done" (reset to 0?)
                            // Our script updates 0->100.
                            // Let's rely on manually stopping loading if we detect completion or handleAnalyze finishes (it awaits the post return?)
                            // Actually POST returns immediately "Analysis started".
                            // So we rely on polling.
                            if (p.percent === 100) {
                                setLoading(false);
                                fetchReport();
                            }
                        }
                    }
                } catch (e) {
                    console.error("Poll error", e);
                }
            }, 1000);
        } else {
            setProgress({ percent: 0, status: 'idle', current_file: '' });
        }
        return () => clearInterval(interval);
    }, [loading]);

    const handleAnalyze = async () => {
        try {
            setLoading(true);
            setProgress({ percent: 0, status: 'starting' });
            await fetch('http://localhost:8000/api/face/analyze', { method: 'POST' });
            // The polling effect will handle updates
        } catch (err) {
            setError(err.message);
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchReport();
    }, []);

    return (
        <div style={{ height: '100%', overflowY: 'auto', padding: '2rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
                <h2 style={{ fontSize: '1.5rem', fontWeight: 'bold' }}>Face Dark Circles History</h2>
                <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                    {loading && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginRight: '1rem' }}>
                            <div style={{ width: '100px', height: '8px', background: 'rgba(255,255,255,0.1)', borderRadius: '4px', overflow: 'hidden' }}>
                                <div style={{
                                    width: `${progress.percent}%`,
                                    height: '100%',
                                    background: '#646cff',
                                    transition: 'width 0.3s ease'
                                }}></div>
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
                                <span style={{ fontSize: '0.9rem', opacity: 0.8 }}>{Number(progress.percent).toFixed(2)}%</span>
                                {progress.current_file && (
                                    <span style={{ fontSize: '0.75rem', opacity: 0.5, maxWidth: '200px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                        {progress.current_file}
                                    </span>
                                )}
                            </div>
                        </div>
                    )}
                    <button
                        onClick={handleAnalyze}
                        disabled={loading}
                        style={{
                            padding: '0.75rem 1.5rem',
                            backgroundColor: 'var(--accent-color, #646cff)',
                            color: 'white',
                            border: 'none',
                            borderRadius: '8px',
                            cursor: loading ? 'wait' : 'pointer',
                            opacity: loading ? 0.7 : 1,
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem'
                        }}
                    >
                        {loading ? 'Analyzing...' : 'Analyze Now'}
                    </button>
                    <button
                        onClick={async () => {
                            try {
                                const res = await fetch('http://localhost:8000/api/face/export_excel');
                                if (res.ok) {
                                    const blob = await res.blob();
                                    const url = window.URL.createObjectURL(blob);
                                    const a = document.createElement('a');
                                    a.href = url;
                                    a.download = "Face_Analysis_History.xlsx";
                                    document.body.appendChild(a);
                                    a.click();
                                    a.remove();
                                } else {
                                    const json = await res.json();
                                    alert('Export failed: ' + (json.error || 'Unknown error'));
                                }
                            } catch (e) {
                                alert('Export failed: ' + e.message);
                            }
                        }}
                        style={{
                            padding: '0.75rem 1.5rem',
                            backgroundColor: '#2ecc71',
                            color: 'white',
                            border: 'none',
                            borderRadius: '8px',
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            marginLeft: '1rem'
                        }}
                    >
                        Export Excel
                    </button>
                </div>
            </div>

            {error && (
                <div style={{
                    padding: '1rem',
                    backgroundColor: 'rgba(255, 87, 87, 0.1)',
                    border: '1px solid var(--error-color, #ff5757)',
                    borderRadius: '8px',
                    marginBottom: '1rem'
                }}>
                    Error: {error}
                </div>
            )}

            {data && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
                    {/* Trend Plot */}
                    <div style={{
                        backgroundColor: 'var(--bg-card, rgba(20, 20, 25, 0.6))',
                        padding: '1.5rem',
                        borderRadius: '16px',
                        border: '1px solid var(--border-color, rgba(255,255,255,0.1))'
                    }}>
                        <h3 style={{ marginBottom: '1rem', opacity: 0.8 }}>Severity Trend</h3>
                        <div style={{ width: '100%', borderRadius: '12px', overflow: 'hidden' }}>
                            <img
                                src={`http://localhost:8000${data.trend_plot}`}
                                alt="Dark Circles Trend"
                                style={{ width: '100%', height: 'auto', display: 'block' }}
                            />
                        </div>
                    </div>

                    {/* Extremes Comparison */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem' }}>
                        {/* Lightest (Best) */}
                        <div style={{
                            backgroundColor: 'rgba(46, 204, 113, 0.1)',
                            padding: '1.5rem',
                            borderRadius: '16px',
                            border: '1px solid rgba(46, 204, 113, 0.3)'
                        }}>
                            <h3 style={{ color: '#2ecc71', marginBottom: '0.5rem' }}>Lightest (Best Condition)</h3>
                            <p style={{ opacity: 0.7, marginBottom: '1rem' }}>{data.lightest.date}</p>
                            <div style={{ borderRadius: '12px', overflow: 'hidden', aspectRatio: '16/9' }}>
                                <img
                                    src={`http://localhost:8000${data.lightest.url}`}
                                    alt="Best Condition"
                                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                                />
                            </div>
                            <p style={{ marginTop: '0.5rem', fontWeight: 'bold' }}>Score: {data.lightest.score.toFixed(2)}</p>
                        </div>

                        {/* Heaviest (Worst) */}
                        <div style={{
                            backgroundColor: 'rgba(231, 76, 60, 0.1)',
                            padding: '1.5rem',
                            borderRadius: '16px',
                            border: '1px solid rgba(231, 76, 60, 0.3)'
                        }}>
                            <h3 style={{ color: '#e74c3c', marginBottom: '0.5rem' }}>Heaviest (Worst Condition)</h3>
                            <p style={{ opacity: 0.7, marginBottom: '1rem' }}>{data.heaviest.date}</p>
                            <div style={{ borderRadius: '12px', overflow: 'hidden', aspectRatio: '16/9' }}>
                                <img
                                    src={`http://localhost:8000${data.heaviest.url}`}
                                    alt="Worst Condition"
                                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                                />
                            </div>
                            <p style={{ marginTop: '0.5rem', fontWeight: 'bold' }}>Score: {data.heaviest.score.toFixed(2)}</p>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default FaceHistory;

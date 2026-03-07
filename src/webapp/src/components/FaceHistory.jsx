import { useEffect, useState } from 'react';
import { getFaceReportState } from '../utils/faceReportState';

const initialProgress = { percent: 0, status: 'idle', current_file: '' };

export default function FaceHistory() {
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(initialProgress);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [reportStatus, setReportStatus] = useState('loading');

  const fetchReport = async ({ showLoading = false } = {}) => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    if (showLoading) {
      setReportStatus('loading');
    }

    try {
      const res = await fetch('http://localhost:8000/api/face/report', {
        signal: controller.signal,
      });
      const json = await res.json();
      const nextState = getFaceReportState(json);

      setData(nextState.data);
      setError(nextState.error);
      setReportStatus(nextState.status);
    } catch (err) {
      setData(null);
      setError(err.name === 'AbortError' ? 'Request timed out while loading the latest report.' : err.message);
      setReportStatus('error');
    } finally {
      clearTimeout(timeoutId);
    }
  };

  useEffect(() => {
    fetchReport({ showLoading: true });
  }, []);

  useEffect(() => {
    if (!loading) {
      setProgress(initialProgress);
      return undefined;
    }

    const interval = setInterval(async () => {
      try {
        const res = await fetch('http://localhost:8000/api/face/progress');
        if (!res.ok) {
          return;
        }

        const nextProgress = await res.json();
        setProgress(nextProgress);

        if (nextProgress.status === 'error') {
          setLoading(false);
          setError(nextProgress.error || 'Face analysis failed.');
          setReportStatus('error');
          return;
        }

        if (nextProgress.percent >= 100) {
          setLoading(false);
          fetchReport();
        }
      } catch (err) {
        console.error('Poll error', err);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [loading]);

  const handleAnalyze = async () => {
    try {
      setLoading(true);
      setError(null);
      setProgress({ percent: 0, status: 'starting', current_file: '' });
      await fetch('http://localhost:8000/api/face/analyze', { method: 'POST' });
    } catch (err) {
      setError(err.message);
      setReportStatus('error');
      setLoading(false);
    }
  };

  const handleExport = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/face/export_excel');
      if (!res.ok) {
        const json = await res.json();
        alert(`Export failed: ${json.error || 'Unknown error'}`);
        return;
      }

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'Face_Analysis_History.xlsx';
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      alert(`Export failed: ${err.message}`);
    }
  };

  const renderBody = () => {
    if (reportStatus === 'loading' && !data) {
      return (
        <div className="glass-panel" style={{ padding: '1.5rem' }}>
          Loading face analysis report...
        </div>
      );
    }

    if (reportStatus === 'empty') {
      return (
        <div className="glass-panel" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
          <strong>No analysis report yet.</strong>
          <span style={{ color: 'var(--text-secondary)' }}>
            Click <strong>Analyze Now</strong> to generate the first cached face report.
          </span>
        </div>
      );
    }

    if (reportStatus === 'error' && !data) {
      return (
        <div
          style={{
            padding: '1rem',
            backgroundColor: 'rgba(255, 87, 87, 0.1)',
            border: '1px solid var(--error-color, #ff5757)',
            borderRadius: '8px',
          }}
        >
          Error: {error}
        </div>
      );
    }

    if (!data) {
      return null;
    }

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
        <div
          className="glass-panel"
          style={{
            padding: '1.5rem',
          }}
        >
          <h3 style={{ marginBottom: '1rem', opacity: 0.8 }}>Severity Trend</h3>
          <div style={{ width: '100%', borderRadius: '12px', overflow: 'hidden' }}>
            <img
              src={`http://localhost:8000${data.trend_plot}`}
              alt="Dark Circles Trend"
              style={{ width: '100%', height: 'auto', display: 'block' }}
            />
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '2rem' }}>
          <div
            style={{
              backgroundColor: 'rgba(46, 204, 113, 0.1)',
              padding: '1.5rem',
              borderRadius: '16px',
              border: '1px solid rgba(46, 204, 113, 0.3)',
            }}
          >
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

          <div
            style={{
              backgroundColor: 'rgba(231, 76, 60, 0.1)',
              padding: '1.5rem',
              borderRadius: '16px',
              border: '1px solid rgba(231, 76, 60, 0.3)',
            }}
          >
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
    );
  };

  return (
    <div style={{ height: '100%', overflowY: 'auto', padding: '2rem' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: '1rem',
          flexWrap: 'wrap',
          marginBottom: '2rem',
        }}
      >
        <h2 style={{ fontSize: '1.5rem', fontWeight: 'bold', margin: 0 }}>Face Dark Circles History</h2>
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
          {loading && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginRight: '1rem' }}>
              <div
                style={{
                  width: '100px',
                  height: '8px',
                  background: 'rgba(255,255,255,0.1)',
                  borderRadius: '4px',
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    width: `${progress.percent}%`,
                    height: '100%',
                    background: '#646cff',
                    transition: 'width 0.3s ease',
                  }}
                />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
                <span style={{ fontSize: '0.9rem', opacity: 0.8 }}>{Number(progress.percent).toFixed(2)}%</span>
                {progress.current_file && (
                  <span
                    style={{
                      fontSize: '0.75rem',
                      opacity: 0.5,
                      maxWidth: '200px',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
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
              gap: '0.5rem',
            }}
          >
            {loading ? 'Analyzing...' : 'Analyze Now'}
          </button>

          <button
            onClick={handleExport}
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
            }}
          >
            Export Excel
          </button>
        </div>
      </div>

      {reportStatus === 'error' && data && (
        <div
          style={{
            padding: '1rem',
            backgroundColor: 'rgba(255, 87, 87, 0.1)',
            border: '1px solid var(--error-color, #ff5757)',
            borderRadius: '8px',
            marginBottom: '1rem',
          }}
        >
          Error: {error}
        </div>
      )}

      {renderBody()}
    </div>
  );
}

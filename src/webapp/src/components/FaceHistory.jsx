import { useEffect, useState } from 'react';
import { getFaceReportState } from '../utils/faceReportState';
import {
  buildBackendUrl,
  fetchBackend,
  fetchBackendJson,
} from '../utils/backendRequest';
import {
  buildChartModel,
} from './faceTrendChart';

const initialProgress = { percent: 0, status: 'idle', current_file: '' };
const initialLiveData = {
  camera_online: false,
  window_seconds: 60,
  latest_score: null,
  latest_datetime: '',
  points: [],
};
const trendViewOrder = ['day', 'week', 'month', 'all'];
const trendCardPalette = ['#00d2d3', '#74b9ff', '#fdcb6e', '#a29bfe'];
const pulseDimensions = { width: 960, height: 180 };
const trendDimensions = { width: 420, height: 180 };
const livePollIntervalMs = 100;

function formatScore(score) {
  return Number.isFinite(Number(score)) ? Number(score).toFixed(2) : '--';
}

function StatPill({ label, value, accent }) {
  return (
    <div
      style={{
        padding: '0.8rem 1rem',
        borderRadius: '14px',
        border: `1px solid ${accent}22`,
        background: `linear-gradient(180deg, ${accent}14 0%, rgba(255,255,255,0.02) 100%)`,
        minWidth: 0,
      }}
    >
      <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: '0.2rem' }}>{label}</div>
      <div style={{ fontSize: '1rem', fontWeight: 700 }}>{value}</div>
    </div>
  );
}

function LineChartSvg({
  ariaLabel,
  width,
  height,
  model,
  stroke,
  background,
  gridStroke,
  gridDasharray,
}) {
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      style={{ width: '100%', height: 'auto', display: 'block' }}
      role="img"
      aria-label={ariaLabel}
    >
      <rect x="0" y="0" width={width} height={height} fill={background} />

      {[0.2, 0.4, 0.6, 0.8].map((ratio) => (
        <line
          key={ratio}
          x1="0"
          y1={height * ratio}
          x2={width}
          y2={height * ratio}
          stroke={gridStroke}
          strokeDasharray={gridDasharray}
        />
      ))}

      <path
        d={model.path}
        fill="none"
        stroke={stroke}
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {model.ticks.map((tick) => (
        <g key={`${ariaLabel}-${tick.label}-${tick.x}`}>
          <line
            x1={tick.x}
            y1={height - 22}
            x2={tick.x}
            y2={height - 14}
            stroke="rgba(255,255,255,0.18)"
          />
          <text
            x={tick.x}
            y={height - 4}
            textAnchor="middle"
            fontSize="11"
            fill="rgba(255,255,255,0.72)"
          >
            {tick.label}
          </text>
        </g>
      ))}
    </svg>
  );
}

function PulseCard({ liveData }) {
  const liveWindowSeconds = Number(liveData?.window_seconds) || 60;
  const liveWindowEndTimestamp = Date.now() / 1000;
  const model = buildChartModel({
    points: liveData?.points || [],
    width: pulseDimensions.width,
    height: pulseDimensions.height,
    minTimestamp: liveWindowEndTimestamp - liveWindowSeconds,
    maxTimestamp: liveWindowEndTimestamp,
  });
  const latestLabel = liveData?.latest_datetime?.slice(0, 19) || '--';
  const cameraStatus = liveData?.camera_online ? 'Online' : 'Offline';
  const emptyMessage = liveData?.camera_online
    ? 'Waiting for passing live dark-circle samples'
    : 'Camera offline';

  return (
    <div
      className="glass-panel"
      style={{
        padding: '1.5rem',
        overflow: 'hidden',
        position: 'relative',
        background: 'radial-gradient(circle at top right, rgba(0,210,211,0.18), transparent 28%), var(--bg-glass)',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          gap: '1rem',
          flexWrap: 'wrap',
          marginBottom: '1rem',
        }}
      >
        <div>
          <div style={{ color: 'var(--text-muted)', fontSize: '0.82rem', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            Live camera score
          </div>
          <h3 style={{ margin: '0.35rem 0 0', fontSize: '1.45rem' }}>Real-time Dark Circle Pulse</h3>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          <StatPill label="Latest Score" value={formatScore(liveData?.latest_score)} accent="#00d2d3" />
          <StatPill label="Latest Time" value={latestLabel} accent="#74b9ff" />
          <StatPill label="Camera" value={cameraStatus} accent="#fdcb6e" />
          <StatPill label="Samples" value={String(model.summary.sampleCount)} accent="#7cf3ff" />
        </div>
      </div>

      <div
        style={{
          borderRadius: '20px',
          overflow: 'hidden',
          border: '1px solid rgba(0, 210, 211, 0.18)',
          background: 'linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.01))',
        }}
      >
        {model.points.length === 0 ? (
          <svg
            viewBox={`0 0 ${pulseDimensions.width} ${pulseDimensions.height}`}
            style={{ width: '100%', height: 'auto', display: 'block' }}
            role="img"
            aria-label="实时黑眼圈分数图"
          >
            <rect x="0" y="0" width={pulseDimensions.width} height={pulseDimensions.height} fill="rgba(4, 10, 16, 0.92)" />
            <text
              x={pulseDimensions.width / 2}
              y={pulseDimensions.height / 2}
              textAnchor="middle"
              fontSize="18"
              fill="rgba(255,255,255,0.56)"
            >
              {emptyMessage}
            </text>
          </svg>
        ) : (
          <div style={{ filter: 'drop-shadow(0 0 12px rgba(0, 210, 211, 0.22))' }}>
            <LineChartSvg
              ariaLabel="实时黑眼圈分数图"
              width={pulseDimensions.width}
              height={pulseDimensions.height}
              model={model}
              stroke="#7cf3ff"
              background="rgba(4, 10, 16, 0.92)"
              gridStroke="rgba(255,255,255,0.08)"
              gridDasharray="6 10"
            />
          </div>
        )}
      </div>
    </div>
  );
}

function TrendCard({ title, accent, points }) {
  const model = buildChartModel({
    points,
    width: trendDimensions.width,
    height: trendDimensions.height,
  });

  return (
    <div
      className="glass-panel"
      style={{
        padding: '1.25rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '1rem',
        minHeight: '320px',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
        <div>
          <div style={{ color: accent, fontSize: '0.8rem', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            Trend window
          </div>
          <h3 style={{ margin: '0.3rem 0 0', fontSize: '1.15rem' }}>{title}</h3>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: '1.25rem', fontWeight: 700 }}>{model.summary.latestScore}</div>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Latest Score</div>
        </div>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))',
          gap: '0.75rem',
        }}
      >
        <StatPill label="Average" value={model.summary.averageScore} accent={accent} />
        <StatPill label="Samples" value={String(model.summary.sampleCount)} accent={accent} />
        <StatPill label="Latest Time" value={model.summary.latestLabel} accent={accent} />
      </div>

      <div
        style={{
          borderRadius: '18px',
          overflow: 'hidden',
          border: `1px solid ${accent}1f`,
          background: 'linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.01))',
          minHeight: '180px',
        }}
      >
        {model.points.length === 0 ? (
          <div
            style={{
              minHeight: '180px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--text-muted)',
              fontSize: '0.95rem',
            }}
          >
            No trend data
          </div>
        ) : (
          <LineChartSvg
            ariaLabel={`${title} dark circle trend`}
            width={trendDimensions.width}
            height={trendDimensions.height}
            model={model}
            stroke={accent}
            background="rgba(6, 10, 20, 0.9)"
            gridStroke="rgba(255,255,255,0.06)"
            gridDasharray="4 10"
          />
        )}
      </div>
    </div>
  );
}

function ExtremeCard({ title, date, score, imageUrl, accent }) {
  return (
    <div
      style={{
        backgroundColor: `${accent}14`,
        padding: '1.5rem',
        borderRadius: '16px',
        border: `1px solid ${accent}55`,
      }}
    >
      <h3 style={{ color: accent, marginBottom: '0.5rem' }}>{title}</h3>
      <p style={{ opacity: 0.7, marginBottom: '1rem' }}>{date || '--'}</p>
      <div style={{ borderRadius: '12px', overflow: 'hidden', aspectRatio: '16/9', background: 'rgba(0,0,0,0.15)' }}>
        {imageUrl ? (
          <img
            src={buildBackendUrl(imageUrl)}
            alt={title}
            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          />
        ) : (
          <div style={{ width: '100%', height: '100%', display: 'grid', placeItems: 'center', color: 'var(--text-muted)' }}>
            No image
          </div>
        )}
      </div>
      <p style={{ marginTop: '0.5rem', fontWeight: 'bold' }}>Score: {formatScore(score)}</p>
    </div>
  );
}

export default function FaceHistory() {
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(initialProgress);
  const [data, setData] = useState(null);
  const [liveData, setLiveData] = useState(initialLiveData);
  const [error, setError] = useState(null);
  const [reportStatus, setReportStatus] = useState('loading');

  const fetchReport = async ({ showLoading = false } = {}) => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    if (showLoading) {
      setReportStatus('loading');
    }

    try {
      const json = await fetchBackendJson('/api/face/report', {
        retryPolicy: 'load',
        signal: controller.signal,
      });
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

  const fetchLive = async () => {
    try {
      const json = await fetchBackendJson('/api/face/live', {
        retryPolicy: 'poll',
      });
      setLiveData({
        camera_online: Boolean(json?.camera_online),
        window_seconds: Number(json?.window_seconds) || 60,
        latest_score: json?.latest_score ?? null,
        latest_datetime: json?.latest_datetime || '',
        points: Array.isArray(json?.points) ? json.points : [],
      });
    } catch (err) {
      console.error('Live face poll error', err);
    }
  };

  useEffect(() => {
    fetchReport({ showLoading: true });
    fetchLive();
  }, []);

  useEffect(() => {
    const interval = setInterval(() => {
      fetchLive();
    }, livePollIntervalMs);

    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!loading) {
      setProgress(initialProgress);
      return undefined;
    }

    const interval = setInterval(async () => {
      try {
        const res = await fetchBackend('/api/face/progress', {
          retryPolicy: 'poll',
          allowHttpError: true,
        });
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
      await fetchBackend('/api/face/analyze', {
        method: 'POST',
        retryPolicy: 'mutation',
      });
    } catch (err) {
      setError(err.message);
      setReportStatus('error');
      setLoading(false);
    }
  };

  const handleExport = async () => {
    try {
      const res = await fetchBackend('/api/face/export_excel', {
        retryPolicy: 'download',
        allowHttpError: true,
      });
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

  const renderHistoryBody = () => {
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
      <>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '1.5rem' }}>
          {trendViewOrder.map((key, index) => (
            <TrendCard
              key={key}
              title={data.trend_views[key].label}
              points={data.trend_views[key].points}
              accent={trendCardPalette[index]}
            />
          ))}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '2rem' }}>
          <ExtremeCard
            title="Lightest (Best Condition)"
            date={data.lightest.date}
            score={data.lightest.score}
            imageUrl={data.lightest.url}
            accent="#2ecc71"
          />

          <ExtremeCard
            title="Heaviest (Worst Condition)"
            date={data.heaviest.date}
            score={data.heaviest.score}
            imageUrl={data.heaviest.url}
            accent="#e74c3c"
          />
        </div>
      </>
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
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 'bold', margin: 0 }}>Face Dark Circles History</h2>
          <div style={{ color: 'var(--text-secondary)', marginTop: '0.35rem' }}>
            Live pulse uses camera scores. Historical charts use saved-photo samples.
          </div>
        </div>
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

      <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
        <PulseCard liveData={liveData} />
        {renderHistoryBody()}
      </div>
    </div>
  );
}

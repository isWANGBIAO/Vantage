import { useEffect, useState } from 'react';
import { getFaceReportState } from '../utils/faceReportState';
import {
  buildBackendUrl,
  fetchBackend,
  fetchBackendJson,
} from '../utils/backendRequest';
import {
  buildChartModel,
  buildPulseFrame,
} from './faceTrendChart';

const initialProgress = { percent: 0, status: 'idle', current_file: '' };
const trendViewOrder = ['day', 'week', 'month', 'all'];
const trendCardPalette = ['#00d2d3', '#74b9ff', '#fdcb6e', '#a29bfe'];
const pulseDimensions = { width: 960, height: 180 };
const trendDimensions = { width: 420, height: 180 };

function formatScore(score) {
  return Number.isFinite(Number(score)) ? Number(score).toFixed(2) : '--';
}

function getLatestPoint(data) {
  const dayPoints = data?.trend_views?.day?.points || [];
  if (dayPoints.length) {
    return dayPoints[dayPoints.length - 1];
  }

  const allPoints = data?.trend_views?.all?.points || [];
  if (allPoints.length) {
    return allPoints[allPoints.length - 1];
  }

  return null;
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

function PulseCard({ latestPoint, frame }) {
  const pulseFrame = buildPulseFrame({
    latestScore: latestPoint?.score,
    frame,
    width: pulseDimensions.width,
    height: pulseDimensions.height,
  });

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
            实时黑眼圈脉冲
          </div>
          <h3 style={{ margin: '0.35rem 0 0', fontSize: '1.45rem' }}>Latest Severity Pulse</h3>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          <StatPill label="最新分数" value={formatScore(latestPoint?.score)} accent="#00d2d3" />
          <StatPill label="最近时间" value={latestPoint?.datetime?.slice(0, 16) || '--'} accent="#74b9ff" />
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
        <svg
          viewBox={`0 0 ${pulseDimensions.width} ${pulseDimensions.height}`}
          style={{ width: '100%', height: 'auto', display: 'block' }}
          role="img"
          aria-label="实时黑眼圈脉冲图"
        >
          <defs>
            <linearGradient id="pulseStroke" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="rgba(0, 210, 211, 0.15)" />
              <stop offset="20%" stopColor="#00d2d3" />
              <stop offset="80%" stopColor="#7cf3ff" />
              <stop offset="100%" stopColor="rgba(124, 243, 255, 0.15)" />
            </linearGradient>
            <filter id="pulseGlow">
              <feGaussianBlur stdDeviation="4" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          <rect x="0" y="0" width={pulseDimensions.width} height={pulseDimensions.height} fill="rgba(4, 10, 16, 0.92)" />

          {[0.2, 0.4, 0.6, 0.8].map((ratio) => (
            <line
              key={ratio}
              x1="0"
              y1={pulseDimensions.height * ratio}
              x2={pulseDimensions.width}
              y2={pulseDimensions.height * ratio}
              stroke="rgba(255,255,255,0.08)"
              strokeDasharray="6 10"
            />
          ))}

          <path
            d={pulseFrame.path}
            fill="none"
            stroke="url(#pulseStroke)"
            strokeWidth="4"
            strokeLinecap="round"
            strokeLinejoin="round"
            filter="url(#pulseGlow)"
          />
        </svg>
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
            趋势窗口
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
        <StatPill label="均值" value={model.summary.averageScore} accent={accent} />
        <StatPill label="样本数" value={String(model.summary.sampleCount)} accent={accent} />
        <StatPill label="最新时间" value={model.summary.latestLabel} accent={accent} />
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
            暂无趋势数据
          </div>
        ) : (
          <svg
            viewBox={`0 0 ${trendDimensions.width} ${trendDimensions.height}`}
            style={{ width: '100%', height: 'auto', display: 'block' }}
            role="img"
            aria-label={`${title}黑眼圈趋势图`}
          >
            <rect x="0" y="0" width={trendDimensions.width} height={trendDimensions.height} fill="rgba(6, 10, 20, 0.9)" />

            {[0.2, 0.4, 0.6, 0.8].map((ratio) => (
              <line
                key={ratio}
                x1="0"
                y1={trendDimensions.height * ratio}
                x2={trendDimensions.width}
                y2={trendDimensions.height * ratio}
                stroke="rgba(255,255,255,0.06)"
                strokeDasharray="4 10"
              />
            ))}

            <path
              d={model.path}
              fill="none"
              stroke={accent}
              strokeWidth="3"
              strokeLinecap="round"
              strokeLinejoin="round"
            />

            {model.points.map((point) => (
              <circle
                key={`${title}-${point.index}-${point.timestamp}`}
                cx={point.x}
                cy={point.y}
                r="4"
                fill={accent}
                stroke="rgba(5,5,8,0.95)"
                strokeWidth="2"
              />
            ))}

            {model.ticks.map((tick) => (
              <g key={`${title}-${tick.label}-${tick.x}`}>
                <line
                  x1={tick.x}
                  y1={trendDimensions.height - 22}
                  x2={tick.x}
                  y2={trendDimensions.height - 14}
                  stroke="rgba(255,255,255,0.18)"
                />
                <text
                  x={tick.x}
                  y={trendDimensions.height - 4}
                  textAnchor="middle"
                  fontSize="11"
                  fill="rgba(255,255,255,0.72)"
                >
                  {tick.label}
                </text>
              </g>
            ))}
          </svg>
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
            暂无图片
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
  const [error, setError] = useState(null);
  const [reportStatus, setReportStatus] = useState('loading');
  const [pulseFrame, setPulseFrame] = useState(0);

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

  useEffect(() => {
    fetchReport({ showLoading: true });
  }, []);

  useEffect(() => {
    const interval = setInterval(() => {
      setPulseFrame((current) => (current + 1) % 1000);
    }, 120);

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

    const latestPoint = getLatestPoint(data);

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
        <PulseCard latestPoint={latestPoint} frame={pulseFrame} />

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
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 'bold', margin: 0 }}>Face Dark Circles History</h2>
          <div style={{ color: 'var(--text-secondary)', marginTop: '0.35rem' }}>
            同页展示实时脉冲、日/周/月/全部历史五张黑眼圈趋势图
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

      {renderBody()}
    </div>
  );
}

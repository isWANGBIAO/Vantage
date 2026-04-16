import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import ReactECharts from 'echarts-for-react';
import { RefreshCw, LineChart, AlertTriangle } from 'lucide-react';
import { fetchBackendJson } from '../utils/backendRequest';
import { buildChartOption, formatSummaryValue } from '../utils/plotFormatters';

function ChartCard({ chart, chartRef }) {
  if (chart.empty) {
    return (
      <section
        ref={chartRef}
        id={chart.id}
        className="glass-panel"
        style={{
          padding: '1.1rem 1.2rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.75rem',
          minHeight: chart.height || 340,
        }}
      >
        <div>
          <h3 style={{ margin: 0, fontSize: '1.05rem' }}>{chart.title}</h3>
          <p style={{ margin: '0.35rem 0 0', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            {chart.description}
          </p>
        </div>
        <div
          style={{
            flex: 1,
            minHeight: 220,
            borderRadius: '16px',
            background: 'rgba(121, 42, 42, 0.18)',
            border: '1px solid rgba(255, 124, 124, 0.22)',
            color: '#f1b4b4',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '0.75rem',
            padding: '1rem',
            textAlign: 'center',
          }}
        >
          <AlertTriangle size={18} />
          <span>{chart.error || 'No data available.'}</span>
        </div>
      </section>
    );
  }

  return (
    <section
      ref={chartRef}
      id={chart.id}
      className="glass-panel"
      style={{
        padding: '1.1rem 1.2rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.9rem',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '1.05rem', color: 'var(--text-primary)' }}>{chart.title}</h3>
            <p style={{ margin: '0.35rem 0 0', color: 'var(--text-secondary)', fontSize: '0.9rem', lineHeight: 1.5 }}>
              {chart.description}
            </p>
          </div>
        </div>
        {chart.summary?.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.55rem' }}>
            {chart.summary.map((item) => (
              <div
                key={`${chart.id}-${item.label}`}
                style={{
                  padding: '0.5rem 0.7rem',
                  borderRadius: '999px',
                  background: 'rgba(255,255,255,0.06)',
                  border: '1px solid rgba(255,255,255,0.08)',
                  display: 'inline-flex',
                  gap: '0.45rem',
                  alignItems: 'center',
                  fontSize: '0.82rem',
                }}
              >
                <span style={{ color: 'var(--text-secondary)' }}>{item.label}</span>
                <strong style={{ color: 'var(--text-primary)' }}>{formatSummaryValue(item)}</strong>
              </div>
            ))}
          </div>
        )}
      </div>

      <div
        style={{
          borderRadius: '20px',
          overflow: 'hidden',
          background: 'radial-gradient(circle at top, rgba(27, 40, 64, 0.95), rgba(10, 16, 29, 0.98))',
          border: '1px solid rgba(255,255,255,0.08)',
        }}
      >
        <ReactECharts
          option={buildChartOption(chart)}
          notMerge
          lazyUpdate
          style={{ width: '100%', height: chart.height || 420 }}
        />
      </div>
    </section>
  );
}

export default function Plots() {
  const [charts, setCharts] = useState([]);
  const [warnings, setWarnings] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [generatedAt, setGeneratedAt] = useState('');
  const chartRefs = useRef({});

  const fetchPlots = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setIsLoading(true);
    setError('');
    try {
      const data = await fetchBackendJson('/api/plots/data', { retryPolicy: 'load' });
      setCharts(Array.isArray(data.charts) ? data.charts : []);
      setWarnings(Array.isArray(data.warnings) ? data.warnings : []);
      setGeneratedAt(data.generated_at || '');
    } catch (err) {
      console.error('Failed to fetch interactive plot data:', err);
      setCharts([]);
      setWarnings([]);
      setError(err?.message || 'Failed to load plot dashboard.');
    } finally {
      if (!silent) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      void fetchPlots();
    }, 0);
    return () => clearTimeout(timer);
  }, [fetchPlots]);

  const refreshPlots = async () => {
    setIsRefreshing(true);
    await fetchPlots({ silent: true });
    setIsRefreshing(false);
  };

  const availableCharts = useMemo(() => charts.filter(Boolean), [charts]);

  const jumpToChart = (chartId) => {
    chartRefs.current[chartId]?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '1rem',
        minHeight: 'calc(100vh - 220px)',
      }}
    >
      <div
        className="glass-panel"
        style={{
          padding: '1rem 1.2rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.9rem',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem' }}>
              <LineChart size={20} color="var(--primary-color)" />
              <h2 style={{ margin: 0, fontSize: '1.25rem' }}>Interactive Plots</h2>
            </div>
            <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.92rem', lineHeight: 1.5 }}>
              Replaced static PNG previews with live interactive charts. All plot categories render on one page with zoom, legend toggle, and export.
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.6rem', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
              <span>{availableCharts.length} charts</span>
              {generatedAt && <span>Generated at {new Date(generatedAt).toLocaleString()}</span>}
            </div>
          </div>

          <button
            onClick={refreshPlots}
            disabled={isRefreshing}
            style={{
              padding: '0.7rem 1.1rem',
              fontSize: '0.9rem',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.55rem',
              background: 'var(--primary-color)',
              color: '#fff',
              border: 'none',
              borderRadius: '10px',
              cursor: isRefreshing ? 'wait' : 'pointer',
              fontWeight: 600,
            }}
          >
            <RefreshCw size={16} className={isRefreshing ? 'spinning' : ''} />
            {isRefreshing ? 'Refreshing...' : 'Refresh Charts'}
          </button>
        </div>

        {availableCharts.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.55rem' }}>
            {availableCharts.map((chart) => (
              <button
                key={chart.id}
                onClick={() => jumpToChart(chart.id)}
                style={{
                  padding: '0.48rem 0.8rem',
                  borderRadius: '999px',
                  border: '1px solid rgba(255,255,255,0.10)',
                  background: 'rgba(255,255,255,0.04)',
                  color: 'var(--text-secondary)',
                  cursor: 'pointer',
                  fontSize: '0.82rem',
                }}
              >
                {chart.title}
              </button>
            ))}
          </div>
        )}
      </div>

      {warnings.length > 0 && (
        <div
          className="glass-panel"
          style={{
            padding: '1rem 1.1rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.8rem',
            border: '1px solid rgba(255, 196, 92, 0.28)',
            background: 'linear-gradient(180deg, rgba(86, 58, 12, 0.34), rgba(39, 28, 10, 0.26))',
          }}
        >
          {warnings.map((warning) => {
            const affectedTitles = availableCharts
              .filter((chart) => warning.affected_chart_ids?.includes(chart.id))
              .map((chart) => chart.title);

            return (
              <div key={warning.id} style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.65rem' }}>
                  <AlertTriangle size={18} color="#ffd27a" style={{ marginTop: '0.1rem', flexShrink: 0 }} />
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                    <strong style={{ color: '#ffe3a6', fontSize: '0.96rem' }}>{warning.title}</strong>
                    <span style={{ color: 'rgba(255, 235, 194, 0.88)', fontSize: '0.88rem', lineHeight: 1.5 }}>
                      {warning.message}
                    </span>
                  </div>
                </div>

                {warning.details?.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
                    {warning.details.map((detail) => (
                      <div
                        key={`${warning.id}-${detail}`}
                        style={{
                          padding: '0.65rem 0.8rem',
                          borderRadius: '12px',
                          background: 'rgba(255, 214, 130, 0.08)',
                          border: '1px solid rgba(255, 214, 130, 0.14)',
                          color: 'rgba(255, 240, 210, 0.9)',
                          fontSize: '0.84rem',
                          lineHeight: 1.5,
                        }}
                      >
                        {detail}
                      </div>
                    ))}
                  </div>
                )}

                {affectedTitles.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                    {affectedTitles.map((title) => (
                      <span
                        key={`${warning.id}-${title}`}
                        style={{
                          padding: '0.42rem 0.72rem',
                          borderRadius: '999px',
                          background: 'rgba(255, 214, 130, 0.1)',
                          border: '1px solid rgba(255, 214, 130, 0.16)',
                          color: '#ffe3a6',
                          fontSize: '0.8rem',
                        }}
                      >
                        受影响图表：{title}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {isLoading ? (
        <div
          className="glass-panel"
          style={{
            minHeight: 220,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--text-secondary)',
          }}
        >
          Loading interactive charts...
        </div>
      ) : error ? (
        <div
          className="glass-panel"
          style={{
            minHeight: 220,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#f1b4b4',
            textAlign: 'center',
            padding: '1rem',
          }}
        >
          {error}
        </div>
      ) : availableCharts.length === 0 ? (
        <div
          className="glass-panel"
          style={{
            minHeight: 220,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--text-secondary)',
          }}
        >
          No chart payload available.
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))',
            gap: '1rem',
            alignItems: 'start',
          }}
        >
          {availableCharts.map((chart) => (
            <ChartCard
              key={chart.id}
              chart={chart}
              chartRef={(node) => {
                if (node) chartRefs.current[chart.id] = node;
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}


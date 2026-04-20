import { useCallback, useEffect, useMemo, useState } from 'react';
import { fetchBackendJson } from '../utils/backendRequest';
import './UsagePanel.css';

const EMPTY_DASHBOARD = {
  summary: {
    session_count: 0,
    completed_call_count: 0,
    failed_call_count: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    total_duration: 0,
    average_duration: 0,
    average_tokens_per_call: 0,
    average_tokens_per_second: 0,
    output_tokens_per_second: 0,
    earliest_call_at: null,
    latest_call_at: null,
  },
  by_source: [],
  by_day: [],
  sessions: [],
  recent_calls: [],
};

function formatCompactNumber(value) {
  const number = Number(value || 0);
  if (number >= 1000000) {
    return `${(number / 1000000).toFixed(2)}M`;
  }
  if (number >= 1000) {
    return `${(number / 1000).toFixed(1)}k`;
  }
  return `${Math.round(number)}`;
}

function formatDuration(seconds) {
  const value = Number(seconds || 0);
  if (value >= 3600) {
    return `${(value / 3600).toFixed(1)}h`;
  }
  if (value >= 60) {
    return `${(value / 60).toFixed(1)}m`;
  }
  return `${value.toFixed(1)}s`;
}

function formatTimestamp(value) {
  if (!value) {
    return '-';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

function formatPercent(value) {
  return `${Number(value || 0).toFixed(1)}%`;
}

function formatRatio(value) {
  return `${Number(value || 0).toFixed(2)} tok/s`;
}

function clampPercent(value) {
  return Math.max(0, Math.min(100, Number(value || 0)));
}

function summarizeSessionId(value) {
  if (!value) {
    return '-';
  }
  return value.length > 14 ? `${value.slice(0, 8)}...${value.slice(-4)}` : value;
}

function toTimestamp(value) {
  if (!value) {
    return Number.NEGATIVE_INFINITY;
  }

  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed;
}

function sortRowsByTimestamp(rows, key) {
  return [...(rows || [])].sort((left, right) => {
    const timestampDifference = toTimestamp(right?.[key]) - toTimestamp(left?.[key]);

    if (timestampDifference !== 0) {
      return timestampDifference;
    }

    const rightIdentity = String(right?.call_id || right?.session_id || right?.source || right?.date || '');
    const leftIdentity = String(left?.call_id || left?.session_id || left?.source || left?.date || '');

    return rightIdentity.localeCompare(leftIdentity);
  });
}

function SummaryCard({ label, value, subValue, accent = 'default' }) {
  return (
    <div className={`usage-summary-item usage-summary-item--${accent}`}>
      <div className="usage-summary-label">{label}</div>
      <div className="usage-summary-value">{value}</div>
      <div className="usage-summary-subvalue">{subValue}</div>
    </div>
  );
}

function ToneChip({ tone = 'neutral', children }) {
  return <span className={`usage-chip usage-chip--${tone}`}>{children}</span>;
}

function DataTable({ columns, rows, emptyMessage }) {
  if (!rows.length) {
    return <div className="usage-empty">{emptyMessage}</div>;
  }

  return (
    <div className="usage-table-wrap">
      <table className="usage-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.id || row.call_id || row.session_id || row.date || `${index}`}>
              {columns.map((column) => (
                <td key={column.key}>{column.render ? column.render(row) : row[column.key]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function UsagePanel() {
  const [dashboard, setDashboard] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const loadUsageDashboard = useCallback(async () => {
    try {
      setError('');
      const data = await fetchBackendJson('/api/usage', { retryPolicy: 'load' });
      setDashboard(data);
    } catch (loadError) {
      console.error('Failed to load usage dashboard.', loadError);
      setError('Failed to load usage dashboard.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadUsageDashboard();

    const intervalId = setInterval(() => {
      void loadUsageDashboard();
    }, 30000);

    return () => clearInterval(intervalId);
  }, [loadUsageDashboard]);

  const usageDashboard = dashboard || EMPTY_DASHBOARD;
  const summary = usageDashboard.summary || EMPTY_DASHBOARD.summary;
  const sourceRows = useMemo(
    () => sortRowsByTimestamp(usageDashboard.by_source || [], 'latest_call_at'),
    [usageDashboard.by_source],
  );
  const dayRows = useMemo(
    () => sortRowsByTimestamp(usageDashboard.by_day || [], 'date'),
    [usageDashboard.by_day],
  );
  const sessionRows = useMemo(
    () => sortRowsByTimestamp(usageDashboard.sessions || [], 'last_call_at'),
    [usageDashboard.sessions],
  );
  const recentCallRows = useMemo(
    () => sortRowsByTimestamp(usageDashboard.recent_calls || [], 'created_at'),
    [usageDashboard.recent_calls],
  );
  const hasUsage = summary.session_count > 0 || summary.completed_call_count > 0 || summary.failed_call_count > 0;
  const totalTokens = Number(summary.total_tokens || 0);
  const promptShare = totalTokens > 0 ? (Number(summary.prompt_tokens || 0) / totalTokens) * 100 : 0;
  const completionShare = totalTokens > 0 ? (Number(summary.completion_tokens || 0) / totalTokens) * 100 : 0;
  const activeSources = sourceRows.filter((row) => (row.completed_call_count || 0) > 0 || (row.failed_call_count || 0) > 0);
  const peakDayTokens = Math.max(...dayRows.map((row) => Number(row.total_tokens || 0)), 0);
  const peakSourceTokens = Math.max(...sourceRows.map((row) => Number(row.total_tokens || 0)), 0);

  const summaryCards = useMemo(() => ([
    {
      label: 'Total Tokens',
      value: formatCompactNumber(summary.total_tokens),
      subValue: `${formatCompactNumber(summary.prompt_tokens)} prompt / ${formatCompactNumber(summary.completion_tokens)} completion`,
      accent: 'strong',
    },
    {
      label: 'Prompt Tokens',
      value: formatCompactNumber(summary.prompt_tokens),
      subValue: `${formatPercent(promptShare)} of total tokens`,
      accent: 'info',
    },
    {
      label: 'Completion Tokens',
      value: formatCompactNumber(summary.completion_tokens),
      subValue: `${formatPercent(completionShare)} of total tokens`,
      accent: 'success',
    },
    {
      label: 'Completion tok/s',
      value: formatRatio(summary.output_tokens_per_second),
      subValue: 'Completion tokens / duration',
      accent: 'calm',
    },
    {
      label: 'Total tok/s',
      value: formatRatio(summary.average_tokens_per_second),
      subValue: 'Prompt + completion / duration',
      accent: 'success',
    },
    {
      label: 'Active Sources',
      value: formatCompactNumber(activeSources.length),
      subValue: `${formatCompactNumber(summary.session_count)} recorded sessions`,
      accent: 'warning',
    },
  ]), [summary, activeSources.length, promptShare, completionShare]);

  return (
    <div className="glass-panel usage-panel">
      <div className="usage-panel-header">
        <div>
          <h2 className="usage-panel-title">Usage Dashboard</h2>
          <div className="usage-secondary-text">Historical model consumption from recorded sessions</div>
        </div>
        <div className="usage-panel-actions">
          {error ? <span className="usage-panel-error">{error}</span> : null}
          <button className="usage-panel-refresh" onClick={() => void loadUsageDashboard()}>
            Refresh
          </button>
        </div>
      </div>

      <div className="usage-panel-content">
        {loading && !dashboard ? <div className="usage-empty">Loading usage dashboard...</div> : null}
        {!loading && !hasUsage ? <div className="usage-empty">No model usage recorded yet.</div> : null}

        <section className="usage-overview">
          <div className="usage-overview-hero">
            <div className="usage-overview-kicker">Usage Overview</div>
            <div className="usage-overview-total">{formatCompactNumber(summary.total_tokens)}</div>
            <div className="usage-overview-caption">Total model tokens recorded across tracked sessions</div>

            <div className="usage-overview-meta">
              <ToneChip tone="neutral">Latest Activity</ToneChip>
              <span className="usage-secondary-text">{formatTimestamp(summary.latest_call_at)}</span>
            </div>

            <div className="usage-meter-group">
              <div className="usage-meter-labels">
                <span>Prompt Share</span>
                <span>{formatPercent(promptShare)}</span>
              </div>
              <div className="usage-meter">
                <div className="usage-meter-fill usage-meter-fill--prompt" style={{ width: `${clampPercent(promptShare)}%` }} />
              </div>
              <div className="usage-meter-labels">
                <span>Completion Share</span>
                <span>{formatPercent(completionShare)}</span>
              </div>
              <div className="usage-meter">
                <div className="usage-meter-fill usage-meter-fill--completion" style={{ width: `${clampPercent(completionShare)}%` }} />
              </div>
            </div>
          </div>

          <div className="usage-summary-grid">
            {summaryCards.map((card) => (
              <SummaryCard
                key={card.label}
                label={card.label}
                value={card.value}
                subValue={card.subValue}
                accent={card.accent}
              />
            ))}
          </div>
        </section>

        <section className="usage-section">
          <h3>By Source</h3>
          {!sourceRows.length ? (
            <div className="usage-empty">No source usage yet.</div>
          ) : (
            <div className="usage-source-list">
              {sourceRows.map((row) => {
                const share = totalTokens > 0 ? (Number(row.total_tokens || 0) / totalTokens) * 100 : 0;
                const promptMix = Number(row.total_tokens || 0) > 0 ? (Number(row.prompt_tokens || 0) / Number(row.total_tokens || 0)) * 100 : 0;
                const completionMix = Number(row.total_tokens || 0) > 0 ? (Number(row.completion_tokens || 0) / Number(row.total_tokens || 0)) * 100 : 0;
                return (
                  <div className="usage-source-row" key={row.source}>
                    <div className="usage-source-primary">
                      <div className="usage-source-heading">
                        <ToneChip tone="neutral">{row.source}</ToneChip>
                        <span className="usage-source-title">{formatCompactNumber(row.total_tokens)} total</span>
                      </div>
                      <div className="usage-source-subline">
                        <span>{row.session_count} sessions</span>
                        <span>{row.completed_call_count} completed</span>
                        <span>{row.failed_call_count} failed</span>
                        <span>Duration {formatDuration(row.total_duration)}</span>
                      </div>
                    </div>
                    <div className="usage-source-analytics">
                      <div className="usage-metric-row">
                        <div className="usage-inline-metric">
                          <span>Prompt</span>
                          <strong>{formatCompactNumber(row.prompt_tokens)}</strong>
                        </div>
                        <div className="usage-inline-metric">
                          <span>Completion</span>
                          <strong>{formatCompactNumber(row.completion_tokens)}</strong>
                        </div>
                        <div className="usage-inline-metric">
                          <span>Total</span>
                          <strong>{formatCompactNumber(row.total_tokens)}</strong>
                        </div>
                        <div className="usage-inline-metric">
                          <span>Completion tok/s</span>
                          <strong>{formatRatio(row.output_tokens_per_second)}</strong>
                        </div>
                        <div className="usage-inline-metric">
                          <span>Total tok/s</span>
                          <strong>{formatRatio(row.average_tokens_per_second)}</strong>
                        </div>
                      </div>
                      <div className="usage-inline-metric">
                        <span>Share</span>
                        <strong>{formatPercent(share)}</strong>
                      </div>
                      <div className="usage-bar-track">
                        <div className="usage-bar-fill usage-bar-fill--source" style={{ width: `${clampPercent((Number(row.total_tokens || 0) / Math.max(peakSourceTokens, 1)) * 100)}%` }} />
                      </div>
                      <div className="usage-source-breakdown">
                        <span>Prompt Share {formatPercent(promptMix)}</span>
                        <span>Completion Share {formatPercent(completionMix)}</span>
                        <span>{formatTimestamp(row.latest_call_at)}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section className="usage-section">
          <h3>Daily Usage</h3>
          {!dayRows.length ? (
            <div className="usage-empty">No daily usage yet.</div>
          ) : (
            <div className="usage-day-list">
              {dayRows.map((row) => (
                <div className="usage-day-row" key={row.date}>
                  <div className="usage-day-date">
                    <div className="usage-day-title">{row.date}</div>
                    <div className="usage-secondary-text">
                      {row.completed_call_count} completed / {row.failed_call_count} failed
                    </div>
                  </div>
                  <div className="usage-day-bar-area">
                    <div className="usage-bar-track usage-bar-track--tall">
                      <div className="usage-bar-fill usage-bar-fill--day" style={{ width: `${clampPercent((Number(row.total_tokens || 0) / Math.max(peakDayTokens, 1)) * 100)}%` }} />
                    </div>
                  </div>
                  <div className="usage-day-metrics">
                    <div className="usage-inline-metric">
                      <span>Prompt</span>
                      <strong>{formatCompactNumber(row.prompt_tokens)}</strong>
                    </div>
                    <div className="usage-inline-metric">
                      <span>Completion</span>
                      <strong>{formatCompactNumber(row.completion_tokens)}</strong>
                    </div>
                    <div className="usage-inline-metric">
                      <span>Total</span>
                      <strong>{formatCompactNumber(row.total_tokens)}</strong>
                    </div>
                    <div className="usage-inline-metric">
                      <span>Duration</span>
                      <strong>{formatDuration(row.total_duration)}</strong>
                    </div>
                    <div className="usage-inline-metric">
                      <span>Completion tok/s</span>
                      <strong>{formatRatio(row.output_tokens_per_second)}</strong>
                    </div>
                    <div className="usage-inline-metric">
                      <span>Total tok/s</span>
                      <strong>{formatRatio(row.average_tokens_per_second)}</strong>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="usage-section">
          <h3>Recent Sessions</h3>
          <DataTable
            emptyMessage="No recent sessions yet."
            rows={sessionRows}
            columns={[
              { key: 'session_id', label: 'Session', render: (row) => summarizeSessionId(row.session_id) },
              { key: 'source', label: 'Source', render: (row) => <ToneChip tone="neutral">{row.source}</ToneChip> },
              { key: 'completed_call_count', label: 'Completed' },
              { key: 'failed_call_count', label: 'Failed' },
              { key: 'prompt_tokens', label: 'Prompt', render: (row) => formatCompactNumber(row.prompt_tokens) },
              { key: 'completion_tokens', label: 'Completion', render: (row) => formatCompactNumber(row.completion_tokens) },
              { key: 'total_tokens', label: 'Total', render: (row) => formatCompactNumber(row.total_tokens) },
              { key: 'output_tokens_per_second', label: 'Completion tok/s', render: (row) => formatRatio(row.output_tokens_per_second) },
              { key: 'average_tokens_per_second', label: 'Total tok/s', render: (row) => formatRatio(row.average_tokens_per_second) },
              {
                key: 'last_status',
                label: 'Last Status',
                render: (row) => (
                  <ToneChip tone={row.last_status === 'failed' ? 'warning' : 'success'}>
                    {row.last_status || 'unknown'}
                  </ToneChip>
                ),
              },
              { key: 'last_call_at', label: 'Last Call', render: (row) => formatTimestamp(row.last_call_at) },
            ]}
          />
        </section>

        <section className="usage-section">
          <h3>Recent Calls</h3>
          <DataTable
            emptyMessage="No recent calls yet."
            rows={recentCallRows}
            columns={[
              { key: 'call_id', label: 'Call', render: (row) => summarizeSessionId(row.call_id) },
              { key: 'source', label: 'Source', render: (row) => <ToneChip tone="neutral">{row.source}</ToneChip> },
              {
                key: 'status',
                label: 'Status',
                render: (row) => (
                  <ToneChip tone={row.status === 'failed' ? 'warning' : 'success'}>
                    {row.status}
                  </ToneChip>
                ),
              },
              { key: 'model', label: 'Model' },
              { key: 'prompt_tokens', label: 'Prompt', render: (row) => formatCompactNumber(row.prompt_tokens) },
              { key: 'completion_tokens', label: 'Completion', render: (row) => formatCompactNumber(row.completion_tokens) },
              { key: 'total_tokens', label: 'Total', render: (row) => formatCompactNumber(row.total_tokens) },
              { key: 'output_tokens_per_second', label: 'Completion tok/s', render: (row) => formatRatio(row.output_tokens_per_second) },
              { key: 'average_tokens_per_second', label: 'Total tok/s', render: (row) => formatRatio(row.average_tokens_per_second) },
              { key: 'duration', label: 'Duration', render: (row) => formatDuration(row.duration) },
              { key: 'created_at', label: 'Started', render: (row) => formatTimestamp(row.created_at) },
            ]}
          />
        </section>
      </div>
    </div>
  );
}

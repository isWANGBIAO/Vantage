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

function SummaryCard({ label, value, subValue }) {
  return (
    <div className="usage-summary-item">
      <div className="usage-summary-label">{label}</div>
      <div className="usage-summary-value">{value}</div>
      <div className="usage-summary-subvalue">{subValue}</div>
    </div>
  );
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
            <tr key={row.id || row.session_id || row.call_id || row.date || `${index}`}>
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
  const hasUsage = summary.session_count > 0 || summary.completed_call_count > 0 || summary.failed_call_count > 0;

  const summaryCards = useMemo(() => ([
    {
      label: 'Total Tokens',
      value: formatCompactNumber(summary.total_tokens),
      subValue: `${formatCompactNumber(summary.prompt_tokens)} prompt / ${formatCompactNumber(summary.completion_tokens)} completion`,
    },
    {
      label: 'Completed Calls',
      value: formatCompactNumber(summary.completed_call_count),
      subValue: `Avg ${formatCompactNumber(summary.average_tokens_per_call)} tokens per call`,
    },
    {
      label: 'Failed Calls',
      value: formatCompactNumber(summary.failed_call_count),
      subValue: `${formatCompactNumber(summary.session_count)} recorded sessions`,
    },
    {
      label: 'Total Duration',
      value: formatDuration(summary.total_duration),
      subValue: `Avg ${formatDuration(summary.average_duration)} per completed call`,
    },
    {
      label: 'Throughput',
      value: `${summary.average_tokens_per_second.toFixed(2)} tok/s`,
      subValue: `Latest ${formatTimestamp(summary.latest_call_at)}`,
    },
  ]), [summary]);

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

        <div className="usage-summary-grid">
          {summaryCards.map((card) => (
            <SummaryCard
              key={card.label}
              label={card.label}
              value={card.value}
              subValue={card.subValue}
            />
          ))}
        </div>

        <section className="usage-section">
          <h3>By Source</h3>
          <DataTable
            emptyMessage="No source usage yet."
            rows={usageDashboard.by_source || []}
            columns={[
              { key: 'source', label: 'Source' },
              { key: 'session_count', label: 'Sessions' },
              { key: 'completed_call_count', label: 'Completed' },
              { key: 'failed_call_count', label: 'Failed' },
              { key: 'total_tokens', label: 'Tokens', render: (row) => formatCompactNumber(row.total_tokens) },
              { key: 'total_duration', label: 'Duration', render: (row) => formatDuration(row.total_duration) },
              { key: 'latest_call_at', label: 'Latest Call', render: (row) => formatTimestamp(row.latest_call_at) },
            ]}
          />
        </section>

        <section className="usage-section">
          <h3>Daily Usage</h3>
          <DataTable
            emptyMessage="No daily usage yet."
            rows={usageDashboard.by_day || []}
            columns={[
              { key: 'date', label: 'Date' },
              { key: 'completed_call_count', label: 'Completed' },
              { key: 'failed_call_count', label: 'Failed' },
              { key: 'total_tokens', label: 'Tokens', render: (row) => formatCompactNumber(row.total_tokens) },
              { key: 'total_duration', label: 'Duration', render: (row) => formatDuration(row.total_duration) },
              { key: 'average_tokens_per_second', label: 'Throughput', render: (row) => `${row.average_tokens_per_second.toFixed(2)} tok/s` },
            ]}
          />
        </section>

        <section className="usage-section">
          <h3>Recent Sessions</h3>
          <DataTable
            emptyMessage="No recent sessions yet."
            rows={usageDashboard.sessions || []}
            columns={[
              { key: 'session_id', label: 'Session' },
              { key: 'source', label: 'Source' },
              { key: 'completed_call_count', label: 'Completed' },
              { key: 'failed_call_count', label: 'Failed' },
              { key: 'total_tokens', label: 'Tokens', render: (row) => formatCompactNumber(row.total_tokens) },
              { key: 'last_status', label: 'Last Status' },
              { key: 'last_call_at', label: 'Last Call', render: (row) => formatTimestamp(row.last_call_at) },
            ]}
          />
        </section>

        <section className="usage-section">
          <h3>Recent Calls</h3>
          <DataTable
            emptyMessage="No recent calls yet."
            rows={usageDashboard.recent_calls || []}
            columns={[
              { key: 'call_id', label: 'Call' },
              { key: 'source', label: 'Source' },
              { key: 'status', label: 'Status' },
              { key: 'model', label: 'Model' },
              { key: 'total_tokens', label: 'Tokens', render: (row) => formatCompactNumber(row.total_tokens) },
              { key: 'duration', label: 'Duration', render: (row) => formatDuration(row.duration) },
              { key: 'created_at', label: 'Started', render: (row) => formatTimestamp(row.created_at) },
            ]}
          />
        </section>
      </div>
    </div>
  );
}

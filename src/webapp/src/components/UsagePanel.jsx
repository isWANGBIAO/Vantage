import { useCallback, useEffect, useMemo, useState } from 'react';
import { fetchBackendJson } from '../utils/backendRequest';
import ReactECharts from '../utils/echarts.js';
import './UsagePanel.css';
import { useDisplayLanguage } from '../context/DisplayLanguageContext.jsx';

const EMPTY_DASHBOARD = {
  summary: {
    session_count: 0,
    completed_call_count: 0,
    failed_call_count: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    prompt_cache_hit_tokens: 0,
    prompt_cache_miss_tokens: 0,
    prompt_cache_hit_rate: null,
    completion_reasoning_tokens: 0,
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
  speed_series: [],
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

function hasRecordedValue(value) {
  return value !== null && value !== undefined;
}

function formatOptionalCompactNumber(value, t) {
  return hasRecordedValue(value) ? formatCompactNumber(value) : t('usage.label.not_recorded');
}

function formatOptionalPercent(value, t) {
  return hasRecordedValue(value) ? formatPercent(value) : t('usage.label.not_recorded');
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

function sortRowsByTimestampAscending(rows, key) {
  return sortRowsByTimestamp(rows, key).reverse();
}

const SPEED_CHART_COLORS = [
  '#10b981',
  '#38bdf8',
  '#f59e0b',
  '#6366f1',
  '#ec4899',
  '#14b8a6',
  '#f97316',
  '#8b5cf6',
];
const HIGH_SPEED_AXIS_MIN_RATE = 1000;
const HIGH_SPEED_AXIS_RATIO = 8;

function getSpeedModelLabel(row, t) {
  return row?.model || row?.default_model || t('usage.label.unknown');
}

function escapeTooltipValue(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function getSpeedValue(row, metricKey) {
  const value = Number(row?.[metricKey] || 0);
  return Number.isFinite(value) ? value : 0;
}

function detectHighSpeedModels(rowsByModel) {
  const peaks = Array.from(rowsByModel.entries()).map(([modelLabel, modelRows]) => ({
    modelLabel,
    peak: Math.max(...modelRows.map((row) => getSpeedValue(row, 'output_tokens_per_second')), 0),
  })).filter((item) => item.peak > 0);

  if (peaks.length < 2) {
    return new Set();
  }

  const baseline = Math.min(...peaks.map((item) => item.peak));
  const threshold = Math.max(HIGH_SPEED_AXIS_MIN_RATE, baseline * HIGH_SPEED_AXIS_RATIO);
  const highSpeedModels = new Set(
    peaks
      .filter((item) => item.peak >= threshold)
      .map((item) => item.modelLabel),
  );

  return highSpeedModels.size === peaks.length ? new Set() : highSpeedModels;
}

function getRobustAxisMax(values) {
  const positiveValues = values
    .map((value) => Number(value || 0))
    .filter((value) => Number.isFinite(value) && value > 0)
    .sort((left, right) => left - right);

  if (!positiveValues.length) {
    return undefined;
  }

  const peak = positiveValues[positiveValues.length - 1];
  if (positiveValues.length < 4) {
    return Math.max(10, peak * 1.15);
  }

  const p90Index = Math.floor((positiveValues.length - 1) * 0.9);
  const robustPeak = positiveValues[p90Index];
  const robustMax = Math.max(10, robustPeak * 1.25);
  return peak > robustMax * 3 ? robustMax : Math.max(10, peak * 1.15);
}

function buildSpeedTrendOption(rows, t) {
  const sortedRows = sortRowsByTimestampAscending(rows, 'created_at');
  const outputLabel = t('usage.speed_trend.output_rate');
  const totalLabel = t('usage.speed_trend.total_rate');
  const rowsByModel = new Map();
  const legendSelected = {};

  sortedRows.forEach((row) => {
    const modelLabel = getSpeedModelLabel(row, t);
    const modelRows = rowsByModel.get(modelLabel) || [];
    modelRows.push(row);
    rowsByModel.set(modelLabel, modelRows);
  });
  const highSpeedModels = detectHighSpeedModels(rowsByModel);
  const normalAxisValues = [];
  const highAxisValues = [];

  const series = Array.from(rowsByModel.entries()).flatMap(([modelLabel, modelRows], index) => {
    const color = SPEED_CHART_COLORS[index % SPEED_CHART_COLORS.length];
    const outputSeriesName = `${modelLabel} - ${outputLabel}`;
    const totalSeriesName = `${modelLabel} - ${totalLabel}`;
    const yAxisIndex = highSpeedModels.has(modelLabel) ? 1 : 0;
    const axisValues = yAxisIndex === 1 ? highAxisValues : normalAxisValues;
    legendSelected[totalSeriesName] = false;
    const buildData = (metricKey, metricLabel, trackAxis = false) => modelRows.map((row) => {
      const value = getSpeedValue(row, metricKey);
      if (trackAxis) {
        axisValues.push(value);
      }
      return {
        value: [row.created_at, value],
        metricLabel,
        row,
      };
    });

    return [
      {
        name: outputSeriesName,
        type: 'line',
        yAxisIndex,
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: {
          width: 2.4,
          color,
        },
        itemStyle: {
          color,
        },
        emphasis: {
          focus: 'series',
        },
        data: buildData('output_tokens_per_second', outputLabel, true),
      },
      {
        name: totalSeriesName,
        type: 'line',
        yAxisIndex,
        smooth: true,
        symbol: 'none',
        lineStyle: {
          width: 1.5,
          type: 'dashed',
          opacity: 0.42,
          color,
        },
        itemStyle: {
          color,
          opacity: 0.42,
        },
        emphasis: {
          focus: 'series',
        },
        data: buildData('average_tokens_per_second', totalLabel),
      },
    ];
  });

  return {
    animationDuration: 260,
    color: SPEED_CHART_COLORS,
    tooltip: {
      trigger: 'axis',
      confine: true,
      formatter: (params) => {
        const items = Array.isArray(params) ? params : [params];
        const firstRow = items.find((item) => item?.data?.row)?.data?.row;
        const lines = [`<strong>${escapeTooltipValue(formatTimestamp(firstRow?.created_at))}</strong>`];

        items.forEach((item) => {
          const row = item?.data?.row;
          if (!row) {
            return;
          }

          const metricLabel = item.data?.metricLabel || outputLabel;
          const value = Array.isArray(item.value) ? item.value[1] : item.value;
          lines.push(
            `${item.marker || ''}${escapeTooltipValue(getSpeedModelLabel(row, t))} ${escapeTooltipValue(metricLabel)}: <strong>${escapeTooltipValue(formatRatio(value))}</strong>`,
          );
        });

        if (firstRow) {
          lines.push(`${escapeTooltipValue(t('usage.speed_trend.tooltip_source'))}: ${escapeTooltipValue(firstRow.source || '-')}`);
          lines.push(`${escapeTooltipValue(t('usage.speed_trend.tooltip_provider'))}: ${escapeTooltipValue(firstRow.provider_route || '-')}`);
          lines.push(`${escapeTooltipValue(t('usage.speed_trend.tooltip_reasoning'))}: ${escapeTooltipValue(firstRow.reasoning_effort || '-')}`);
          lines.push(`${escapeTooltipValue(t('usage.speed_trend.tooltip_duration'))}: ${escapeTooltipValue(formatDuration(firstRow.duration))}`);
          lines.push(
            `${escapeTooltipValue(t('usage.speed_trend.tooltip_tokens'))}: ${escapeTooltipValue(t('usage.label.prompt'))} ${escapeTooltipValue(formatCompactNumber(firstRow.prompt_tokens))} / ${escapeTooltipValue(t('usage.label.completion'))} ${escapeTooltipValue(formatCompactNumber(firstRow.completion_tokens))} / ${escapeTooltipValue(t('usage.label.total'))} ${escapeTooltipValue(formatCompactNumber(firstRow.total_tokens))}`,
          );
          lines.push(
            `${escapeTooltipValue(t('usage.speed_trend.tooltip_cache'))}: ${escapeTooltipValue(t('usage.label.cache_hit'))} ${escapeTooltipValue(formatOptionalCompactNumber(firstRow.prompt_cache_hit_tokens, t))} / ${escapeTooltipValue(t('usage.label.cache_miss'))} ${escapeTooltipValue(formatOptionalCompactNumber(firstRow.prompt_cache_miss_tokens, t))} / ${escapeTooltipValue(t('usage.label.cache_hit_rate'))} ${escapeTooltipValue(formatOptionalPercent(firstRow.prompt_cache_hit_rate, t))}`,
          );
          lines.push(
            `${escapeTooltipValue(t('usage.speed_trend.tooltip_reasoning_tokens'))}: ${escapeTooltipValue(formatOptionalCompactNumber(firstRow.completion_reasoning_tokens, t))}`,
          );
        }

        return lines.join('<br/>');
      },
    },
    legend: {
      type: 'scroll',
      top: 0,
      left: 0,
      right: 0,
      selected: legendSelected,
      itemWidth: 18,
      itemHeight: 8,
      textStyle: {
        color: '#64748b',
        fontSize: 11,
      },
      pageIconColor: '#64748b',
      pageTextStyle: {
        color: '#64748b',
      },
    },
    grid: {
      top: 52,
      right: highSpeedModels.size ? 68 : 20,
      bottom: 70,
      left: 56,
    },
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: 0,
        filterMode: 'none',
        start: 0,
        end: 100,
      },
      {
        type: 'slider',
        xAxisIndex: 0,
        filterMode: 'none',
        height: 22,
        bottom: 8,
        start: 0,
        end: 100,
        borderColor: 'rgba(148, 163, 184, 0.28)',
        fillerColor: 'rgba(20, 184, 166, 0.12)',
        handleStyle: {
          color: '#14b8a6',
        },
        textStyle: {
          color: '#64748b',
        },
      },
    ],
    xAxis: {
      type: 'time',
      axisLabel: {
        color: '#64748b',
      },
      axisLine: {
        lineStyle: {
          color: '#cbd5e1',
        },
      },
      splitLine: {
        show: false,
      },
    },
    yAxis: [
      {
        type: 'value',
        name: 'tok/s',
        max: getRobustAxisMax(normalAxisValues),
        nameTextStyle: {
          color: '#64748b',
        },
        axisLabel: {
          color: '#64748b',
        },
        splitLine: {
          lineStyle: {
            color: 'rgba(148, 163, 184, 0.18)',
          },
        },
      },
      {
        type: 'value',
        name: t('usage.speed_trend.high_speed_axis'),
        show: highSpeedModels.size > 0,
        max: getRobustAxisMax(highAxisValues),
        nameTextStyle: {
          color: '#64748b',
        },
        axisLabel: {
          color: '#64748b',
        },
        splitLine: {
          show: false,
        },
      },
    ],
    series,
  };
}

const USAGE_STATUS_COPY_KEYS = {
  completed: 'usage.status.completed',
  failed: 'usage.status.failed',
  ignored: 'usage.status.ignored',
  started: 'usage.status.started',
};

function formatUsageStatus(status, t) {
  if (!status) {
    return t('usage.status.unknown');
  }

  const copyKey = USAGE_STATUS_COPY_KEYS[status];
  return copyKey ? t(copyKey) : status;
}

function usageStatusTone(status) {
  if (status === 'failed') {
    return 'warning';
  }
  if (status === 'completed') {
    return 'success';
  }
  return 'neutral';
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

function UsageSpeedTrendChart({ rows, t }) {
  const option = useMemo(() => buildSpeedTrendOption(rows, t), [rows, t]);

  return (
    <section className="usage-speed-card">
      <div className="usage-speed-header">
        <div>
          <h3>{t('usage.speed_trend.title')}</h3>
          <div className="usage-secondary-text">{t('usage.speed_trend.subtitle')}</div>
        </div>
      </div>

      {!rows.length ? (
        <div className="usage-speed-empty">{t('usage.speed_trend.empty')}</div>
      ) : (
        <ReactECharts
          className="usage-speed-chart"
          option={option}
          notMerge
          lazyUpdate
          style={{ height: 320 }}
        />
      )}
    </section>
  );
}

export default function UsagePanel({ isVisible = true } = {}) {
  const { t } = useDisplayLanguage();
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
      setError(t('usage.error.load'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (!isVisible) {
      return undefined;
    }

    void loadUsageDashboard();

    const intervalId = setInterval(() => {
      void loadUsageDashboard();
    }, 30000);

    return () => clearInterval(intervalId);
  }, [isVisible, loadUsageDashboard]);

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
  const speedRows = useMemo(
    () => sortRowsByTimestampAscending(usageDashboard.speed_series || [], 'created_at'),
    [usageDashboard.speed_series],
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
      label: t('usage.summary.total_tokens'),
      value: formatCompactNumber(summary.total_tokens),
      subValue: t('usage.summary.prompt_split', {
        prompt: formatCompactNumber(summary.prompt_tokens),
        completion: formatCompactNumber(summary.completion_tokens),
      }),
      accent: 'strong',
    },
    {
      label: t('usage.summary.prompt_tokens'),
      value: formatCompactNumber(summary.prompt_tokens),
      subValue: t('usage.summary.percent_of_total', { value: formatPercent(promptShare) }),
      accent: 'info',
    },
    {
      label: t('usage.summary.completion_tokens'),
      value: formatCompactNumber(summary.completion_tokens),
      subValue: t('usage.summary.percent_of_total', { value: formatPercent(completionShare) }),
      accent: 'success',
    },
    {
      label: t('usage.summary.completion_rate'),
      value: formatRatio(summary.output_tokens_per_second),
      subValue: t('usage.summary.completion_duration'),
      accent: 'calm',
    },
    {
      label: t('usage.summary.total_rate'),
      value: formatRatio(summary.average_tokens_per_second),
      subValue: t('usage.summary.total_duration'),
      accent: 'success',
    },
    {
      label: t('usage.summary.cache_hit'),
      value: formatOptionalCompactNumber(summary.prompt_cache_hit_tokens, t),
      subValue: t('usage.summary.cache_split', {
        hit: formatOptionalCompactNumber(summary.prompt_cache_hit_tokens, t),
        miss: formatOptionalCompactNumber(summary.prompt_cache_miss_tokens, t),
      }),
      accent: 'info',
    },
    {
      label: t('usage.summary.cache_hit_rate'),
      value: formatOptionalPercent(summary.prompt_cache_hit_rate, t),
      subValue: t('usage.summary.cache_hit_rate_detail'),
      accent: 'calm',
    },
    {
      label: t('usage.summary.reasoning_tokens'),
      value: formatOptionalCompactNumber(summary.completion_reasoning_tokens, t),
      subValue: t('usage.summary.reasoning_tokens_detail'),
      accent: 'warning',
    },
    {
      label: t('usage.summary.active_sources'),
      value: formatCompactNumber(activeSources.length),
      subValue: t('usage.summary.recorded_sessions', { value: formatCompactNumber(summary.session_count) }),
      accent: 'warning',
    },
  ]), [summary, activeSources.length, promptShare, completionShare, t]);

  return (
    <div className="glass-panel usage-panel">
      <div className="usage-panel-header">
        <div>
          <h2 className="usage-panel-title">{t('usage.title')}</h2>
          <div className="usage-secondary-text">{t('usage.subtitle')}</div>
        </div>
        <div className="usage-panel-actions">
          {error ? <span className="usage-panel-error">{error}</span> : null}
          <button className="usage-panel-refresh" onClick={() => void loadUsageDashboard()}>
            {t('usage.refresh')}
          </button>
        </div>
      </div>

      <div className="usage-panel-content">
        {loading && !dashboard ? <div className="usage-empty">{t('usage.loading')}</div> : null}
        {!loading && !hasUsage ? <div className="usage-empty">{t('usage.empty')}</div> : null}

        <section className="usage-overview">
          <div className="usage-overview-hero">
            <div className="usage-overview-kicker">{t('usage.overview')}</div>
            <div className="usage-overview-total">{formatCompactNumber(summary.total_tokens)}</div>
            <div className="usage-overview-caption">{t('usage.total_caption')}</div>

            <div className="usage-overview-meta">
              <ToneChip tone="neutral">{t('usage.latest_activity')}</ToneChip>
              <span className="usage-secondary-text">{formatTimestamp(summary.latest_call_at)}</span>
            </div>

            <div className="usage-meter-group">
              <div className="usage-meter-labels">
                <span>{t('usage.prompt_share')}</span>
                <span>{formatPercent(promptShare)}</span>
              </div>
              <div className="usage-meter">
                <div className="usage-meter-fill usage-meter-fill--prompt" style={{ width: `${clampPercent(promptShare)}%` }} />
              </div>
              <div className="usage-meter-labels">
                <span>{t('usage.completion_share')}</span>
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

        <UsageSpeedTrendChart rows={speedRows} t={t} />

        <section className="usage-section">
          <h3>{t('usage.by_source')}</h3>
          {!sourceRows.length ? (
            <div className="usage-empty">{t('usage.by_source.empty')}</div>
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
                        <span className="usage-source-title">
                          {t('usage.source.total', { value: formatCompactNumber(row.total_tokens) })}
                        </span>
                      </div>
                      <div className="usage-source-subline">
                        <span>{t('usage.source.sessions', { value: row.session_count })}</span>
                        <span>{t('usage.source.completed', { value: row.completed_call_count })}</span>
                        <span>{t('usage.source.failed', { value: row.failed_call_count })}</span>
                        <span>{t('usage.source.duration', { value: formatDuration(row.total_duration) })}</span>
                      </div>
                    </div>
                    <div className="usage-source-analytics">
                      <div className="usage-metric-row">
                        <div className="usage-inline-metric">
                          <span>{t('usage.label.prompt')}</span>
                          <strong>{formatCompactNumber(row.prompt_tokens)}</strong>
                        </div>
                        <div className="usage-inline-metric">
                          <span>{t('usage.label.completion')}</span>
                          <strong>{formatCompactNumber(row.completion_tokens)}</strong>
                        </div>
                        <div className="usage-inline-metric">
                          <span>{t('usage.label.total')}</span>
                          <strong>{formatCompactNumber(row.total_tokens)}</strong>
                        </div>
                        <div className="usage-inline-metric">
                          <span>{t('usage.label.completion_rate')}</span>
                          <strong>{formatRatio(row.output_tokens_per_second)}</strong>
                        </div>
                        <div className="usage-inline-metric">
                          <span>{t('usage.label.total_rate')}</span>
                          <strong>{formatRatio(row.average_tokens_per_second)}</strong>
                        </div>
                      </div>
                      <div className="usage-inline-metric">
                        <span>{t('usage.label.share')}</span>
                        <strong>{formatPercent(share)}</strong>
                      </div>
                      <div className="usage-bar-track">
                        <div className="usage-bar-fill usage-bar-fill--source" style={{ width: `${clampPercent((Number(row.total_tokens || 0) / Math.max(peakSourceTokens, 1)) * 100)}%` }} />
                      </div>
                      <div className="usage-source-breakdown">
                        <span>{t('usage.label.prompt_share')} {formatPercent(promptMix)}</span>
                        <span>{t('usage.label.completion_share')} {formatPercent(completionMix)}</span>
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
          <h3>{t('usage.daily')}</h3>
          {!dayRows.length ? (
            <div className="usage-empty">{t('usage.daily.empty')}</div>
          ) : (
            <div className="usage-day-list">
              {dayRows.map((row) => (
                <div className="usage-day-row" key={row.date}>
                  <div className="usage-day-date">
                    <div className="usage-day-title">{row.date}</div>
                    <div className="usage-secondary-text">
                      {t('usage.daily.completed_failed', {
                        completed: row.completed_call_count,
                        failed: row.failed_call_count,
                      })}
                    </div>
                  </div>
                  <div className="usage-day-bar-area">
                    <div className="usage-bar-track usage-bar-track--tall">
                      <div className="usage-bar-fill usage-bar-fill--day" style={{ width: `${clampPercent((Number(row.total_tokens || 0) / Math.max(peakDayTokens, 1)) * 100)}%` }} />
                    </div>
                  </div>
                  <div className="usage-day-metrics">
                    <div className="usage-inline-metric">
                      <span>{t('usage.label.prompt')}</span>
                      <strong>{formatCompactNumber(row.prompt_tokens)}</strong>
                    </div>
                    <div className="usage-inline-metric">
                      <span>{t('usage.label.completion')}</span>
                      <strong>{formatCompactNumber(row.completion_tokens)}</strong>
                    </div>
                    <div className="usage-inline-metric">
                      <span>{t('usage.label.total')}</span>
                      <strong>{formatCompactNumber(row.total_tokens)}</strong>
                    </div>
                    <div className="usage-inline-metric">
                      <span>{t('usage.label.duration')}</span>
                      <strong>{formatDuration(row.total_duration)}</strong>
                    </div>
                    <div className="usage-inline-metric">
                      <span>{t('usage.label.completion_rate')}</span>
                      <strong>{formatRatio(row.output_tokens_per_second)}</strong>
                    </div>
                    <div className="usage-inline-metric">
                      <span>{t('usage.label.total_rate')}</span>
                      <strong>{formatRatio(row.average_tokens_per_second)}</strong>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="usage-section">
          <h3>
            {t('usage.recent_sessions')}
            <span className="usage-section-scope">{t('usage.cache_scope.session_total')}</span>
          </h3>
          <DataTable
            emptyMessage={t('usage.recent_sessions.empty')}
            rows={sessionRows}
            columns={[
              { key: 'session_id', label: t('usage.label.session'), render: (row) => summarizeSessionId(row.session_id) },
              { key: 'source', label: t('usage.label.source'), render: (row) => <ToneChip tone="neutral">{row.source}</ToneChip> },
              { key: 'completed_call_count', label: t('usage.label.completed') },
              { key: 'failed_call_count', label: t('usage.label.failed') },
              { key: 'prompt_tokens', label: t('usage.label.prompt'), render: (row) => formatCompactNumber(row.prompt_tokens) },
              { key: 'completion_tokens', label: t('usage.label.completion'), render: (row) => formatCompactNumber(row.completion_tokens) },
              { key: 'total_tokens', label: t('usage.label.total'), render: (row) => formatCompactNumber(row.total_tokens) },
              { key: 'prompt_cache_hit_tokens', label: t('usage.label.cache_hit'), render: (row) => formatOptionalCompactNumber(row.prompt_cache_hit_tokens, t) },
              { key: 'prompt_cache_miss_tokens', label: t('usage.label.cache_miss'), render: (row) => formatOptionalCompactNumber(row.prompt_cache_miss_tokens, t) },
              { key: 'prompt_cache_hit_rate', label: t('usage.label.cache_hit_rate'), render: (row) => formatOptionalPercent(row.prompt_cache_hit_rate, t) },
              { key: 'completion_reasoning_tokens', label: t('usage.label.reasoning_tokens'), render: (row) => formatOptionalCompactNumber(row.completion_reasoning_tokens, t) },
              { key: 'output_tokens_per_second', label: t('usage.label.completion_rate'), render: (row) => formatRatio(row.output_tokens_per_second) },
              { key: 'average_tokens_per_second', label: t('usage.label.total_rate'), render: (row) => formatRatio(row.average_tokens_per_second) },
              {
                key: 'last_status',
                label: t('usage.label.last_status'),
                render: (row) => (
                  <ToneChip tone={usageStatusTone(row.last_status)}>
                    {formatUsageStatus(row.last_status, t)}
                  </ToneChip>
                ),
              },
              { key: 'last_call_at', label: t('usage.label.last_call'), render: (row) => formatTimestamp(row.last_call_at) },
            ]}
          />
        </section>

        <section className="usage-section">
          <h3>
            {t('usage.recent_calls')}
            <span className="usage-section-scope">{t('usage.cache_scope.single_request')}</span>
          </h3>
          <DataTable
            emptyMessage={t('usage.recent_calls.empty')}
            rows={recentCallRows}
            columns={[
              { key: 'call_id', label: t('usage.label.call'), render: (row) => summarizeSessionId(row.call_id) },
              { key: 'source', label: t('usage.label.source'), render: (row) => <ToneChip tone="neutral">{row.source}</ToneChip> },
              {
                key: 'status',
                label: t('usage.label.status'),
                render: (row) => (
                  <ToneChip tone={usageStatusTone(row.status)}>
                    {formatUsageStatus(row.status, t)}
                  </ToneChip>
                ),
              },
              { key: 'model', label: t('usage.label.model') },
              { key: 'provider_route', label: t('usage.label.provider'), render: (row) => row.provider_route || '-' },
              { key: 'prompt_tokens', label: t('usage.label.prompt'), render: (row) => formatCompactNumber(row.prompt_tokens) },
              { key: 'completion_tokens', label: t('usage.label.completion'), render: (row) => formatCompactNumber(row.completion_tokens) },
              { key: 'total_tokens', label: t('usage.label.total'), render: (row) => formatCompactNumber(row.total_tokens) },
              { key: 'prompt_cache_hit_tokens', label: t('usage.label.cache_hit'), render: (row) => formatOptionalCompactNumber(row.prompt_cache_hit_tokens, t) },
              { key: 'prompt_cache_miss_tokens', label: t('usage.label.cache_miss'), render: (row) => formatOptionalCompactNumber(row.prompt_cache_miss_tokens, t) },
              { key: 'prompt_cache_hit_rate', label: t('usage.label.cache_hit_rate'), render: (row) => formatOptionalPercent(row.prompt_cache_hit_rate, t) },
              { key: 'completion_reasoning_tokens', label: t('usage.label.reasoning_tokens'), render: (row) => formatOptionalCompactNumber(row.completion_reasoning_tokens, t) },
              { key: 'output_tokens_per_second', label: t('usage.label.completion_rate'), render: (row) => formatRatio(row.output_tokens_per_second) },
              { key: 'average_tokens_per_second', label: t('usage.label.total_rate'), render: (row) => formatRatio(row.average_tokens_per_second) },
              { key: 'duration', label: t('usage.label.duration'), render: (row) => formatDuration(row.duration) },
              { key: 'created_at', label: t('usage.label.started'), render: (row) => formatTimestamp(row.created_at) },
            ]}
          />
        </section>
      </div>
    </div>
  );
}

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import ReactECharts from '../utils/echarts.js';
import { AlertTriangle, LineChart, RefreshCw } from 'lucide-react';

import { fetchBackendJson } from '../utils/backendRequest';
import { buildChartOption, formatSummaryValue } from '../utils/plotFormatters';
import { getChartTheme } from '../utils/chartTheme.js';
import { useDisplayLanguage } from '../context/DisplayLanguageContext.jsx';
import { localizePlotChart, localizePlotWarnings } from '../utils/plotLocalization.js';

const SECTION_DEFINITIONS = [
  {
    key: 'health',
    accent: '#46a17d',
    leadIds: ['sleep-schedule', 'weight-bodyfat', 'time-allocation'],
    supportIds: ['time-screen-remaining', 'time-averages', 'time-delta', 'radar-goal'],
  },
  {
    key: 'performance',
    accent: '#4f7cff',
    leadIds: ['running'],
    supportIds: ['running-form', 'running-hrc', 'hhh-frequency', 'hhh-interval'],
  },
  {
    key: 'finance',
    accent: '#f59f54',
    leadIds: ['balance'],
    supportIds: [],
  },
];

function formatGeneratedAt(value, locale, t) {
  if (!value) {
    return t('plots.generated_none');
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return date.toLocaleString(locale, {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function getWarningDetails(warning) {
  if (Array.isArray(warning?.details) && warning.details.length) {
    return warning.details;
  }

  if (Array.isArray(warning?.rows) && warning.rows.length) {
    return warning.rows;
  }

  if (warning?.detail) {
    return [warning.detail];
  }

  if (warning?.message) {
    return [warning.message];
  }

  return [];
}

function getWarningCharts(warning) {
  if (Array.isArray(warning?.charts)) {
    return warning.charts;
  }

  if (Array.isArray(warning?.chart_ids)) {
    return warning.chart_ids;
  }

  if (Array.isArray(warning?.affectedCharts)) {
    return warning.affectedCharts;
  }

  return [];
}

function buildSections(charts, t) {
  const chartMap = new Map(charts.map((chart) => [chart.id, chart]));
  const used = new Set();
  const sections = [];

  SECTION_DEFINITIONS.forEach((section) => {
    const leadCharts = section.leadIds.map((chartId) => chartMap.get(chartId)).filter(Boolean);
    const supportCharts = section.supportIds.map((chartId) => chartMap.get(chartId)).filter(Boolean);

    [...leadCharts, ...supportCharts].forEach((chart) => used.add(chart.id));

    if (leadCharts.length || supportCharts.length) {
      sections.push({
        ...section,
        title: t(`plots.section.${section.key}.title`),
        description: t(`plots.section.${section.key}.desc`),
        leadCharts,
        supportCharts,
      });
    }
  });

  const remainingCharts = charts.filter((chart) => !used.has(chart.id));

  if (remainingCharts.length) {
    sections.push({
      key: 'other',
      title: t('plots.section.other.title'),
      description: t('plots.section.other.desc'),
      accent: '#8e7f6a',
      leadCharts: remainingCharts,
      supportCharts: [],
    });
  }

  return sections;
}

function useChartMountReady() {
  const containerRef = useRef(null);
  const [isReady, setIsReady] = useState(false);

  useLayoutEffect(() => {
    const node = containerRef.current;
    if (!node) {
      return undefined;
    }

    let frameId = null;

    const update = () => {
      const { width, height } = node.getBoundingClientRect();
      setIsReady(width > 0 && height > 0);
    };

    const scheduleUpdate = () => {
      if (frameId != null) {
        cancelAnimationFrame(frameId);
      }
      frameId = requestAnimationFrame(update);
    };

    update();

    if (typeof ResizeObserver === 'function') {
      const observer = new ResizeObserver(() => {
        scheduleUpdate();
      });
      observer.observe(node);

      return () => {
        if (frameId != null) {
          cancelAnimationFrame(frameId);
        }
        observer.disconnect();
      };
    }

    window.addEventListener('resize', scheduleUpdate);

    return () => {
      if (frameId != null) {
        cancelAnimationFrame(frameId);
      }
      window.removeEventListener('resize', scheduleUpdate);
    };
  }, []);

  return {
    containerRef,
    isReady,
  };
}

function SummaryPill({ label, value, tone = 'default', themeTokens }) {
  const tones = {
    default: {
      background: themeTokens.summaryBackground,
      border: `1px solid ${themeTokens.summaryBorder}`,
      color: themeTokens.summaryText,
    },
    warning: {
      background: themeTokens.summaryWarningBackground,
      border: `1px solid ${themeTokens.summaryWarningBorder}`,
      color: themeTokens.summaryWarningText,
    },
  };

  const palette = tones[tone] || tones.default;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        minWidth: 112,
        padding: '12px 14px',
        borderRadius: 18,
        ...palette,
      }}
    >
      <span style={{ fontSize: 11, color: themeTokens.summaryLabel }}>{label}</span>
      <strong style={{ fontSize: 17, fontWeight: 700 }}>{value}</strong>
    </div>
  );
}

function WarningPanel({ warnings, onSelectChart, availableChartIds, themeTokens, t }) {
  if (!warnings.length) {
    return null;
  }

  return (
    <section
      style={{
        display: 'grid',
        gap: 14,
        marginBottom: 28,
        padding: 20,
        borderRadius: 28,
        background: themeTokens.warningPanelBackground,
        border: `1px solid ${themeTokens.warningPanelBorder}`,
        boxShadow: themeTokens.warningPanelShadow,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 38,
            height: 38,
            borderRadius: 12,
            background: themeTokens.warningPanelIconBackground,
            color: themeTokens.warningPanelIconText,
          }}
        >
          <AlertTriangle size={18} />
        </div>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: themeTokens.warningPanelTitle }}>{t('plots.warning.title')}</div>
          <div style={{ marginTop: 4, fontSize: 13, color: themeTokens.warningPanelText }}>
            {t('plots.warning.body')}
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gap: 12 }}>
        {warnings.map((warning, index) => {
          const details = getWarningDetails(warning);
          const chartIds = getWarningCharts(warning).filter((chartId) => availableChartIds.has(chartId));

          return (
            <div
              key={`${warning?.title || 'warning'}-${index}`}
              style={{
                display: 'grid',
                gap: 10,
                padding: 16,
                borderRadius: 22,
                background: themeTokens.warningPanelCardBackground,
                border: `1px solid ${themeTokens.warningPanelCardBorder}`,
              }}
            >
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: themeTokens.warningPanelTitle }}>
                  {warning?.title || t('plots.warning.fallback_title')}
                </div>
                {warning?.message ? (
                  <div style={{ marginTop: 4, fontSize: 13, color: themeTokens.warningPanelText }}>{warning.message}</div>
                ) : null}
              </div>

              {details.length ? (
                <div style={{ display: 'grid', gap: 8 }}>
                  {details.map((detail) => (
                    <div
                      key={detail}
                      style={{
                        padding: '10px 12px',
                        borderRadius: 14,
                        background: themeTokens.warningPanelDetailBackground,
                        color: themeTokens.warningPanelDetailText,
                        fontSize: 13,
                        fontFamily: 'ui-monospace, SFMono-Regular, Consolas, monospace',
                      }}
                    >
                      {detail}
                    </div>
                  ))}
                </div>
              ) : null}

              {chartIds.length ? (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {chartIds.map((chartId) => (
                    <button
                      key={chartId}
                      onClick={() => onSelectChart(chartId)}
                      style={{
                        border: 'none',
                        cursor: 'pointer',
                        padding: '8px 12px',
                        borderRadius: 999,
                        background: themeTokens.warningPanelActionBackground,
                        color: themeTokens.warningPanelActionText,
                        fontSize: 12,
                        fontWeight: 600,
                      }}
                    >
                      {t('plots.warning.jump', { chartId })}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function ChartInlineWarnings({ warnings, themeTokens, t }) {
  if (!warnings.length) {
    return null;
  }

  const detailLines = warnings.flatMap((warning) => {
    const details = getWarningDetails(warning);
    if (details.length) {
      return details.map((detail) => ({
        title: warning?.title || t('plots.warning.fallback_title'),
        detail,
      }));
    }
    return [
      {
        title: warning?.title || t('plots.warning.fallback_title'),
        detail: warning?.message || t('plots.inline_warning.detail_fallback'),
      },
    ];
  });

  const visibleLines = detailLines.slice(0, 4);
  const remainingCount = detailLines.length - visibleLines.length;

  return (
    <div
      style={{
        display: 'grid',
        gap: 10,
        padding: 14,
        borderRadius: 20,
        background: themeTokens.inlineWarningBackground,
        border: `1px solid ${themeTokens.inlineWarningBorder}`,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: themeTokens.warningPanelDetailText }}>
        <AlertTriangle size={16} />
        <strong style={{ fontSize: 13 }}>{t('plots.inline_warning.title')}</strong>
      </div>
      <div style={{ display: 'grid', gap: 8 }}>
        {visibleLines.map((item, index) => (
          <div
            key={`${item.title}-${index}`}
            style={{
              padding: '10px 12px',
              borderRadius: 14,
              background: themeTokens.inlineWarningItemBackground,
              color: themeTokens.warningPanelDetailText,
              fontSize: 12,
              lineHeight: 1.6,
              fontFamily: 'ui-monospace, SFMono-Regular, Consolas, monospace',
            }}
          >
            <strong>{item.title}</strong>
            <div>{item.detail}</div>
          </div>
        ))}
        {remainingCount > 0 ? (
          <div style={{ fontSize: 12, color: themeTokens.inlineWarningMuted }}>
            {t('plots.inline_warning.remaining', { count: remainingCount })}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ChartCard({
  chart,
  chartRef,
  featured = false,
  accent = '#46a17d',
  hasWarning = false,
  chartWarnings = [],
  theme = 'dark',
  themeTokens,
  t,
  language,
}) {
  const chartHeight = featured ? Math.max(chart?.height || 420, 500) : Math.max(chart?.height || 360, 390);
  const summaries = Array.isArray(chart?.summary) ? chart.summary : [];
  const { containerRef, isReady } = useChartMountReady();

  return (
    <article
      ref={chartRef}
      id={`plot-${chart?.id}`}
      style={{
        display: 'grid',
        gap: 18,
        padding: featured ? 24 : 20,
        borderRadius: featured ? 30 : 26,
        background: themeTokens.cardBackground,
        border: `1px solid ${featured ? themeTokens.cardStrongBorder : themeTokens.cardBorder}`,
        boxShadow: featured
          ? themeTokens.cardStrongShadow
          : themeTokens.cardShadow,
        backdropFilter: 'blur(14px)',
      }}
    >
      <div style={{ display: 'grid', gap: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start' }}>
          <div style={{ display: 'grid', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  padding: '6px 10px',
                  borderRadius: 999,
                  background: `${accent}14`,
                  color: accent,
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: '0.04em',
                  textTransform: 'uppercase',
                }}
              >
                {t(featured ? 'plots.chart.primary' : 'plots.chart.support')}
              </span>
              {hasWarning ? (
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '6px 10px',
                    borderRadius: 999,
                    background: themeTokens.warningBadgeBackground,
                    color: themeTokens.warningBadgeText,
                    fontSize: 11,
                    fontWeight: 700,
                  }}
                >
                  <AlertTriangle size={12} />
                  {t('plots.chart.warning')}
                </span>
              ) : null}
            </div>

            <div style={{ display: 'grid', gap: 6 }}>
              <h3
                style={{
                  margin: 0,
                  fontSize: featured ? 28 : 22,
                  fontWeight: 800,
                  letterSpacing: '-0.03em',
                  color: themeTokens.cardTitle,
                }}
              >
                {chart?.title}
              </h3>
              {chart?.description ? (
                <p
                  style={{
                    margin: 0,
                    maxWidth: 760,
                    lineHeight: 1.65,
                    fontSize: 14,
                    color: themeTokens.cardText,
                  }}
                >
                  {chart.description}
                </p>
              ) : null}
            </div>
          </div>

          <div
            style={{
              width: 16,
              height: 16,
              flexShrink: 0,
              marginTop: 8,
              borderRadius: 999,
              background: accent,
              boxShadow: `0 0 0 8px ${accent}18`,
            }}
          />
        </div>

        {summaries.length ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {summaries.map((item) => (
              <SummaryPill
                key={`${chart.id}-${item.label}`}
                label={item.label}
                value={formatSummaryValue(item, language)}
                themeTokens={themeTokens}
              />
            ))}
          </div>
        ) : null}
        {chartWarnings.length ? <ChartInlineWarnings warnings={chartWarnings} themeTokens={themeTokens} t={t} /> : null}
      </div>

      {chart?.empty ? (
        <div
          style={{
            display: 'grid',
            placeItems: 'center',
            minHeight: 220,
            borderRadius: 24,
            background: themeTokens.emptyBackground,
            border: `1px dashed ${themeTokens.emptyBorder}`,
            color: themeTokens.emptyText,
            textAlign: 'center',
            padding: 24,
          }}
        >
          <div style={{ display: 'grid', gap: 10 }}>
            <AlertTriangle size={24} style={{ justifySelf: 'center' }} />
            <strong>{chart?.message || t('plots.empty_chart')}</strong>
          </div>
        </div>
      ) : (
        <div
          ref={containerRef}
          style={{
            borderRadius: 28,
            padding: featured ? 18 : 14,
            minHeight: chartHeight + (featured ? 36 : 28),
            background: themeTokens.chartSurfaceBackground,
            border: `1px solid ${themeTokens.chartSurfaceBorder}`,
          }}
        >
          {isReady ? (
            <ReactECharts option={buildChartOption(chart, theme, language)} notMerge lazyUpdate style={{ width: '100%', height: chartHeight }} />
          ) : (
            <div
              style={{
                height: chartHeight,
                borderRadius: 20,
                background: themeTokens.chartSkeletonBackground,
              }}
            />
          )}
        </div>
      )}
    </article>
  );
}

function SectionBlock({ section, chartRefs, warningCharts, warningMap, theme, themeTokens, t }) {
  return (
    <section style={{ display: 'grid', gap: 20 }}>
      <div
        style={{
          display: 'grid',
          gap: 10,
          paddingBottom: 14,
          borderBottom: `1px solid ${themeTokens.sectionDivider}`,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span
            style={{
              width: 12,
              height: 12,
              borderRadius: 999,
              background: section.accent,
              boxShadow: `0 0 0 8px ${section.accent}16`,
            }}
          />
          <div style={{ fontSize: 24, fontWeight: 800, letterSpacing: '-0.03em', color: themeTokens.sectionTitle }}>{section.title}</div>
        </div>
        <div style={{ fontSize: 14, lineHeight: 1.65, color: themeTokens.sectionText, maxWidth: 840 }}>
          {section.description}
        </div>
      </div>

      {section.leadCharts.length ? (
        <div
          style={{
            display: 'grid',
            gap: 18,
            gridTemplateColumns: 'minmax(0, 1fr)',
          }}
        >
          {section.leadCharts.map((chart) => (
            <ChartCard
              key={chart.id}
              chart={chart}
              chartRef={(node) => {
                if (node) {
                  chartRefs.current.set(chart.id, node);
                } else {
                  chartRefs.current.delete(chart.id);
                }
              }}
              featured
              accent={section.accent}
              hasWarning={warningCharts.has(chart.id)}
              chartWarnings={warningMap.get(chart.id) || []}
              theme={theme}
              themeTokens={themeTokens}
              t={t}
              language={section.language}
            />
          ))}
        </div>
      ) : null}

      {section.supportCharts.length ? (
        <div
          style={{
            display: 'grid',
            gap: 16,
            gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 620px), 1fr))',
          }}
        >
          {section.supportCharts.map((chart) => (
            <ChartCard
              key={chart.id}
              chart={chart}
              chartRef={(node) => {
                if (node) {
                  chartRefs.current.set(chart.id, node);
                } else {
                  chartRefs.current.delete(chart.id);
                }
              }}
              accent={section.accent}
              hasWarning={warningCharts.has(chart.id)}
              chartWarnings={warningMap.get(chart.id) || []}
              theme={theme}
              themeTokens={themeTokens}
              t={t}
              language={section.language}
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}

export default function Plots({ theme = 'dark' }) {
  const { effectiveLanguage, t } = useDisplayLanguage();
  const [charts, setCharts] = useState([]);
  const [warnings, setWarnings] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [generatedAt, setGeneratedAt] = useState(null);
  const chartRefs = useRef(new Map());
  const themeTokens = useMemo(() => getChartTheme(theme), [theme]);

  const fetchPlots = useCallback(async (refresh = false) => {
    if (refresh) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }

    setError(null);

    try {
      if (refresh) {
        await fetchBackendJson('/api/plots/refresh', {
          method: 'POST',
          retryPolicy: 'mutation',
        });
      }

      const data = await fetchBackendJson('/api/plots/data');
      setCharts(Array.isArray(data?.charts) ? data.charts : []);
      setWarnings(Array.isArray(data?.warnings) ? data.warnings : []);
      setGeneratedAt(data?.generated_at || null);
    } catch (fetchError) {
      setError(fetchError.message || t('plots.error_load'));
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [t]);

  useEffect(() => {
    fetchPlots();
  }, [fetchPlots]);

  const localizedCharts = useMemo(
    () => charts.map((chart) => localizePlotChart(chart, effectiveLanguage)),
    [charts, effectiveLanguage],
  );
  const localizedWarnings = useMemo(
    () => localizePlotWarnings(warnings, effectiveLanguage),
    [warnings, effectiveLanguage],
  );
  const visibleCharts = useMemo(() => localizedCharts.filter((chart) => chart.id !== 'balance'), [localizedCharts]);
  const visibleChartIds = useMemo(() => new Set(visibleCharts.map((chart) => chart.id)), [visibleCharts]);
  const sections = useMemo(
    () => buildSections(visibleCharts, t).map((section) => ({ ...section, language: effectiveLanguage })),
    [effectiveLanguage, t, visibleCharts],
  );

  const warningCharts = useMemo(() => {
    const ids = new Set();
    localizedWarnings.forEach((warning) => {
      getWarningCharts(warning).forEach((chartId) => ids.add(chartId));
    });
    return ids;
  }, [localizedWarnings]);

  const warningMap = useMemo(() => {
    const chartWarningMap = new Map();
    localizedWarnings.forEach((warning) => {
      getWarningCharts(warning).forEach((chartId) => {
        if (!chartWarningMap.has(chartId)) {
          chartWarningMap.set(chartId, []);
        }
        chartWarningMap.get(chartId).push(warning);
      });
    });
    return chartWarningMap;
  }, [localizedWarnings]);

  const navigationCharts = useMemo(() => {
    const orderedCharts = [];

    sections.forEach((section) => {
      section.leadCharts.forEach((chart) => orderedCharts.push(chart));
      section.supportCharts.forEach((chart) => orderedCharts.push(chart));
    });

    return orderedCharts;
  }, [sections]);

  const sectionCount = sections.length;
  const warningCount = localizedWarnings.length;
  const generatedText = formatGeneratedAt(generatedAt, effectiveLanguage, t);

  const scrollToChart = useCallback((chartId) => {
    const node = chartRefs.current.get(chartId);
    if (!node) {
      return;
    }

    node.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    });
  }, []);

  return (
    <div
      style={{
        minHeight: '100%',
        background: themeTokens.pageBackground,
      }}
    >
      <div
        style={{
          maxWidth: 1480,
          margin: '0 auto',
          padding: '32px 28px 48px',
          display: 'grid',
          gap: 28,
        }}
      >
        <header
          style={{
            display: 'grid',
            gap: 22,
            padding: 28,
            borderRadius: 34,
            background: themeTokens.pageHeaderBackground,
            border: `1px solid ${themeTokens.pageHeaderBorder}`,
            boxShadow: themeTokens.pageHeaderShadow,
            backdropFilter: 'blur(18px)',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 18, alignItems: 'flex-start', flexWrap: 'wrap' }}>
            <div style={{ display: 'grid', gap: 12, maxWidth: 860 }}>
              <div
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '8px 12px',
                  borderRadius: 999,
                  background: themeTokens.heroChipBackground,
                  color: themeTokens.heroChipText,
                  fontSize: 12,
                  fontWeight: 700,
                  width: 'fit-content',
                  letterSpacing: '0.03em',
                }}
              >
                <LineChart size={14} />
                {t('plots.hero.chip')}
              </div>
              <div style={{ display: 'grid', gap: 8 }}>
                <h1
                  style={{
                    margin: 0,
                    fontSize: 'clamp(34px, 4vw, 52px)',
                    lineHeight: 1,
                    letterSpacing: '-0.05em',
                    color: themeTokens.pageTitle,
                  }}
                >
                  {t('plots.hero.title')}
                </h1>
                <p
                  style={{
                    margin: 0,
                    fontSize: 15,
                    lineHeight: 1.75,
                    color: themeTokens.pageText,
                    maxWidth: 760,
                  }}
                >
                  {t('plots.hero.desc')}
                </p>
              </div>
            </div>

            <button
              onClick={() => fetchPlots(true)}
              disabled={isRefreshing}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 10,
                border: 'none',
                cursor: isRefreshing ? 'default' : 'pointer',
                padding: '14px 18px',
                borderRadius: 18,
                background: isRefreshing
                  ? themeTokens.refreshButtonDisabledBackground
                  : themeTokens.refreshButtonBackground,
                color: themeTokens.refreshButtonText,
                fontSize: 13,
                fontWeight: 700,
                boxShadow: isRefreshing ? 'none' : themeTokens.cardShadow,
              }}
            >
              <RefreshCw size={15} />
              {isRefreshing ? t('plots.refreshing') : t('plots.refresh')}
            </button>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            <SummaryPill label={t('plots.summary.chart_count')} value={`${visibleCharts.length}`} themeTokens={themeTokens} />
            <SummaryPill label={t('plots.summary.section_count')} value={`${sectionCount}`} themeTokens={themeTokens} />
            <SummaryPill
              label={t('plots.summary.warning_count')}
              value={`${warningCount}`}
              tone={warningCount ? 'warning' : 'default'}
              themeTokens={themeTokens}
            />
            <SummaryPill label={t('plots.summary.generated_at')} value={generatedText} themeTokens={themeTokens} />
          </div>

          {navigationCharts.length ? (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {navigationCharts.map((chart) => (
                <button
                  key={chart.id}
                  onClick={() => scrollToChart(chart.id)}
                  style={{
                    border: 'none',
                    cursor: 'pointer',
                    padding: '10px 14px',
                    borderRadius: 999,
                    background: warningCharts.has(chart.id)
                      ? themeTokens.navChipWarningBackground
                      : themeTokens.navChipBackground,
                    color: warningCharts.has(chart.id) ? themeTokens.navChipWarningText : themeTokens.navChipText,
                    fontSize: 12,
                    fontWeight: 700,
                    boxShadow: `inset 0 0 0 1px ${themeTokens.navChipBorder}`,
                  }}
                >
                  {chart.title}
                </button>
              ))}
            </div>
          ) : null}
        </header>

        {error ? (
          <section
            style={{
              padding: 18,
              borderRadius: 24,
              background: themeTokens.errorBackground,
              border: `1px solid ${themeTokens.errorBorder}`,
              color: themeTokens.errorText,
            }}
          >
            <div style={{ fontWeight: 700 }}>{t('plots.error_title')}</div>
            <div style={{ marginTop: 6, fontSize: 14 }}>{error}</div>
          </section>
        ) : null}

        <WarningPanel
          warnings={localizedWarnings}
          onSelectChart={scrollToChart}
          availableChartIds={visibleChartIds}
          themeTokens={themeTokens}
          t={t}
        />

        {isLoading ? (
          <section
            style={{
              display: 'grid',
              gap: 16,
              gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
            }}
          >
            {Array.from({ length: 4 }).map((_, index) => (
              <div
                key={`loading-${index}`}
                style={{
                  minHeight: index < 2 ? 420 : 320,
                  borderRadius: 28,
                  background: themeTokens.loadingBackground,
                  border: `1px solid ${themeTokens.cardBorder}`,
                }}
              />
            ))}
          </section>
        ) : null}

        {!isLoading && !visibleCharts.length ? (
          <section
            style={{
              padding: 32,
              borderRadius: 28,
              background: themeTokens.emptySectionBackground,
              border: `1px solid ${themeTokens.emptySectionBorder}`,
              color: themeTokens.emptySectionText,
            }}
          >
            {t('plots.empty')}
          </section>
        ) : null}

        {!isLoading && sections.length ? (
          <main style={{ display: 'grid', gap: 34 }}>
            {sections.map((section) => (
              <SectionBlock
                key={section.key}
                section={section}
                chartRefs={chartRefs}
                warningCharts={warningCharts}
                warningMap={warningMap}
                theme={theme}
                themeTokens={themeTokens}
                t={t}
              />
            ))}
          </main>
        ) : null}
      </div>
    </div>
  );
}

import { useLayoutEffect, useRef, useState } from 'react';
import ReactECharts from '../utils/echarts.js';
import { AlertTriangle } from 'lucide-react';

import { buildChartOption, formatSummaryValue } from '../utils/plotFormatters';
import { getChartTheme } from '../utils/chartTheme.js';
import { useDisplayLanguage } from '../context/DisplayLanguageContext.jsx';
import { localizePlotChart } from '../utils/plotLocalization.js';

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

function SummaryPill({ label, value, themeTokens }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        minWidth: 112,
        padding: '12px 14px',
        borderRadius: 18,
        background: themeTokens.summaryBackground,
        border: `1px solid ${themeTokens.summaryBorder}`,
        color: themeTokens.summaryText,
      }}
    >
      <span style={{ fontSize: 11, color: themeTokens.summaryLabel }}>{label}</span>
      <strong style={{ fontSize: 17, fontWeight: 700 }}>{value}</strong>
    </div>
  );
}

export default function PlotChartCard({
  chart,
  chartRef,
  featured = false,
  accent = '#46a17d',
  hasWarning = false,
  eyebrow,
  chartHeight,
  theme = 'dark',
}) {
  const { effectiveLanguage, t } = useDisplayLanguage();
  const themeTokens = getChartTheme(theme);
  const localizedChart = localizePlotChart(chart, effectiveLanguage);
  const resolvedHeight =
    chartHeight ?? (featured ? Math.max(localizedChart?.height || 420, 500) : Math.max(localizedChart?.height || 360, 390));
  const summaries = Array.isArray(localizedChart?.summary) ? localizedChart.summary : [];
  const roleLabel = eyebrow === undefined
    ? t(featured ? 'plots.chart.primary' : 'plots.chart.support')
    : eyebrow;
  const { containerRef, isReady } = useChartMountReady();

  return (
    <article
      ref={chartRef}
      id={`plot-${localizedChart?.id || 'chart'}`}
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
              {roleLabel ? (
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
                  {roleLabel}
                </span>
              ) : null}
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
                  letterSpacing: 0,
                  color: themeTokens.cardTitle,
                }}
              >
                {localizedChart?.title}
              </h3>
              {localizedChart?.description ? (
                <p
                  style={{
                    margin: 0,
                    maxWidth: 760,
                    lineHeight: 1.65,
                    fontSize: 14,
                    color: themeTokens.cardText,
                  }}
                >
                  {localizedChart.description}
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
                key={`${localizedChart?.id || 'chart'}-${item.label}`}
                label={item.label}
                value={formatSummaryValue(item, effectiveLanguage)}
                themeTokens={themeTokens}
              />
            ))}
          </div>
        ) : null}
      </div>

      {localizedChart?.empty ? (
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
            <strong>{localizedChart?.message || t('plots.empty_chart')}</strong>
          </div>
        </div>
      ) : (
        <div
          ref={containerRef}
          style={{
            borderRadius: 28,
            padding: featured ? 18 : 14,
            minHeight: resolvedHeight + (featured ? 36 : 28),
            background: themeTokens.chartSurfaceBackground,
            border: `1px solid ${themeTokens.chartSurfaceBorder}`,
          }}
        >
          {isReady ? (
            <ReactECharts
              option={buildChartOption(localizedChart, theme, effectiveLanguage)}
              notMerge
              lazyUpdate
              style={{ width: '100%', height: resolvedHeight }}
            />
          ) : (
            <div
              style={{
                height: resolvedHeight,
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

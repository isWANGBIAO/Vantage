import { useLayoutEffect, useRef, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { AlertTriangle } from 'lucide-react';

import { buildChartOption, formatSummaryValue } from '../utils/plotFormatters';

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

function SummaryPill({ label, value }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        minWidth: 112,
        padding: '12px 14px',
        borderRadius: 18,
        background: 'rgba(255, 255, 255, 0.8)',
        border: '1px solid rgba(16, 35, 28, 0.08)',
        color: '#173328',
      }}
    >
      <span style={{ fontSize: 11, color: 'rgba(23, 51, 40, 0.68)' }}>{label}</span>
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
}) {
  const resolvedHeight =
    chartHeight ?? (featured ? Math.max(chart?.height || 420, 500) : Math.max(chart?.height || 360, 390));
  const summaries = Array.isArray(chart?.summary) ? chart.summary : [];
  const roleLabel = eyebrow === undefined ? (featured ? 'primary chart' : 'support chart') : eyebrow;
  const { containerRef, isReady } = useChartMountReady();

  return (
    <article
      ref={chartRef}
      id={`plot-${chart?.id || 'chart'}`}
      style={{
        display: 'grid',
        gap: 18,
        padding: featured ? 24 : 20,
        borderRadius: featured ? 30 : 26,
        background: 'rgba(255, 255, 255, 0.82)',
        border: `1px solid ${featured ? 'rgba(16, 35, 28, 0.08)' : 'rgba(16, 35, 28, 0.06)'}`,
        boxShadow: featured
          ? '0 26px 60px rgba(11, 27, 21, 0.12)'
          : '0 18px 40px rgba(11, 27, 21, 0.08)',
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
                    background: 'rgba(255, 243, 214, 0.86)',
                    color: '#8f5600',
                    fontSize: 11,
                    fontWeight: 700,
                  }}
                >
                  <AlertTriangle size={12} />
                  warning
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
                  color: '#10231c',
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
                    color: 'rgba(16, 35, 28, 0.72)',
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
              <SummaryPill key={`${chart?.id || 'chart'}-${item.label}`} label={item.label} value={formatSummaryValue(item)} />
            ))}
          </div>
        ) : null}
      </div>

      {chart?.empty ? (
        <div
          style={{
            display: 'grid',
            placeItems: 'center',
            minHeight: 220,
            borderRadius: 24,
            background: 'rgba(250, 238, 238, 0.82)',
            border: '1px dashed rgba(162, 56, 56, 0.24)',
            color: '#7c2d2d',
            textAlign: 'center',
            padding: 24,
          }}
        >
          <div style={{ display: 'grid', gap: 10 }}>
            <AlertTriangle size={24} style={{ justifySelf: 'center' }} />
            <strong>{chart?.message || '暂无可用数据'}</strong>
          </div>
        </div>
      ) : (
        <div
          ref={containerRef}
          style={{
            borderRadius: 28,
            padding: featured ? 18 : 14,
            minHeight: resolvedHeight + (featured ? 36 : 28),
            background:
              'radial-gradient(circle at top left, rgba(255, 255, 255, 0.88), rgba(243, 248, 245, 0.76) 42%, rgba(236, 244, 239, 0.96) 100%)',
            border: '1px solid rgba(16, 35, 28, 0.06)',
          }}
        >
          {isReady ? (
            <ReactECharts option={buildChartOption(chart)} notMerge lazyUpdate style={{ width: '100%', height: resolvedHeight }} />
          ) : (
            <div
              style={{
                height: resolvedHeight,
                borderRadius: 20,
                background:
                  'linear-gradient(135deg, rgba(255, 255, 255, 0.44) 0%, rgba(235, 242, 237, 0.72) 100%)',
              }}
            />
          )}
        </div>
      )}
    </article>
  );
}

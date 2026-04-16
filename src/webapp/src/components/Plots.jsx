import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { AlertTriangle, LineChart, RefreshCw } from 'lucide-react';

import { fetchBackendJson } from '../utils/backendRequest';
import { buildChartOption, formatSummaryValue } from '../utils/plotFormatters';

const SECTION_DEFINITIONS = [
  {
    key: 'health',
    title: '健康主视图',
    description: '先看体重、体脂和时间配置，快速判断健康行为有没有失衡。',
    accent: '#46a17d',
    leadIds: ['weight-bodyfat', 'time-allocation'],
    supportIds: ['time-screen-remaining', 'time-averages', 'time-delta', 'radar-goal'],
  },
  {
    key: 'performance',
    title: '行为与训练',
    description: '把跑步趋势和 HHH 节律放在一起看，更容易发现执行强度与恢复节奏。',
    accent: '#4f7cff',
    leadIds: ['running'],
    supportIds: ['hhh-frequency', 'hhh-interval'],
  },
  {
    key: 'finance',
    title: '财务波动',
    description: '保留财务图，但下沉到最后一层，不再和健康主图争抢注意力。',
    accent: '#f59f54',
    leadIds: ['balance'],
    supportIds: [],
  },
];

const CHART_SECTION_MAP = SECTION_DEFINITIONS.reduce((accumulator, section) => {
  [...section.leadIds, ...section.supportIds].forEach((chartId) => {
    accumulator[chartId] = section.key;
  });
  return accumulator;
}, {});

function formatGeneratedAt(value) {
  if (!value) {
    return '未生成';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return date.toLocaleString('zh-CN', {
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

function buildSections(charts) {
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
        leadCharts,
        supportCharts,
      });
    }
  });

  const remainingCharts = charts.filter((chart) => !used.has(chart.id));

  if (remainingCharts.length) {
    sections.push({
      key: 'other',
      title: '其他图表',
      description: '保留未分组图表，避免数据缺失。',
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

function SummaryPill({ label, value, tone = 'default' }) {
  const tones = {
    default: {
      background: 'rgba(255, 255, 255, 0.8)',
      border: '1px solid rgba(16, 35, 28, 0.08)',
      color: '#173328',
    },
    warning: {
      background: 'rgba(255, 241, 213, 0.92)',
      border: '1px solid rgba(210, 138, 32, 0.18)',
      color: '#7a4d02',
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
      <span style={{ fontSize: 11, color: 'rgba(23, 51, 40, 0.68)' }}>{label}</span>
      <strong style={{ fontSize: 17, fontWeight: 700 }}>{value}</strong>
    </div>
  );
}

function WarningPanel({ warnings, onSelectChart }) {
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
        background:
          'linear-gradient(135deg, rgba(255, 248, 232, 0.96) 0%, rgba(255, 241, 213, 0.92) 100%)',
        border: '1px solid rgba(214, 154, 54, 0.24)',
        boxShadow: '0 18px 40px rgba(124, 78, 8, 0.08)',
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
            background: 'rgba(214, 154, 54, 0.14)',
            color: '#9a5d00',
          }}
        >
          <AlertTriangle size={18} />
        </div>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#6f4301' }}>发现异常数据，相关图表已标注警告</div>
          <div style={{ marginTop: 4, fontSize: 13, color: 'rgba(111, 67, 1, 0.78)' }}>
            请先修正原始表格，再执行 refresh charts。未修正前，这些图表会继续提示异常。
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gap: 12 }}>
        {warnings.map((warning, index) => {
          const details = getWarningDetails(warning);
          const chartIds = getWarningCharts(warning);

          return (
            <div
              key={`${warning?.title || 'warning'}-${index}`}
              style={{
                display: 'grid',
                gap: 10,
                padding: 16,
                borderRadius: 22,
                background: 'rgba(255, 255, 255, 0.58)',
                border: '1px solid rgba(214, 154, 54, 0.14)',
              }}
            >
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: '#6f4301' }}>
                  {warning?.title || '异常数据'}
                </div>
                {warning?.message ? (
                  <div style={{ marginTop: 4, fontSize: 13, color: 'rgba(111, 67, 1, 0.76)' }}>{warning.message}</div>
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
                        background: 'rgba(255, 247, 230, 0.92)',
                        color: '#7a4d02',
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
                        background: 'rgba(176, 116, 18, 0.1)',
                        color: '#6f4301',
                        fontSize: 12,
                        fontWeight: 600,
                      }}
                    >
                      跳转到 {chartId}
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

function ChartCard({ chart, chartRef, featured = false, accent = '#46a17d', hasWarning = false }) {
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
                {featured ? 'primary chart' : 'support chart'}
              </span>
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
              <SummaryPill key={`${chart.id}-${item.label}`} label={item.label} value={formatSummaryValue(item)} />
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
            minHeight: chartHeight + (featured ? 36 : 28),
            background:
              'radial-gradient(circle at top left, rgba(255, 255, 255, 0.88), rgba(243, 248, 245, 0.76) 42%, rgba(236, 244, 239, 0.96) 100%)',
            border: '1px solid rgba(16, 35, 28, 0.06)',
          }}
        >
          {isReady ? (
            <ReactECharts option={buildChartOption(chart)} notMerge lazyUpdate style={{ width: '100%', height: chartHeight }} />
          ) : (
            <div
              style={{
                height: chartHeight,
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

function SectionBlock({ section, chartRefs, warningCharts }) {
  return (
    <section style={{ display: 'grid', gap: 20 }}>
      <div
        style={{
          display: 'grid',
          gap: 10,
          paddingBottom: 14,
          borderBottom: '1px solid rgba(16, 35, 28, 0.08)',
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
          <div style={{ fontSize: 24, fontWeight: 800, letterSpacing: '-0.03em', color: '#10231c' }}>{section.title}</div>
        </div>
        <div style={{ fontSize: 14, lineHeight: 1.65, color: 'rgba(16, 35, 28, 0.68)', maxWidth: 840 }}>
          {section.description}
        </div>
      </div>

      {section.leadCharts.length ? (
        <div
          style={{
            display: 'grid',
            gap: 18,
            gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))',
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
            />
          ))}
        </div>
      ) : null}

      {section.supportCharts.length ? (
        <div
          style={{
            display: 'grid',
            gap: 16,
            gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
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
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}

export default function Plots() {
  const [charts, setCharts] = useState([]);
  const [warnings, setWarnings] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [generatedAt, setGeneratedAt] = useState(null);
  const chartRefs = useRef(new Map());

  const fetchPlots = useCallback(async (refresh = false) => {
    if (refresh) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }

    setError(null);

    try {
      const data = await fetchBackendJson(`/api/plots/data${refresh ? '?refresh=1' : ''}`);
      setCharts(Array.isArray(data?.charts) ? data.charts : []);
      setWarnings(Array.isArray(data?.warnings) ? data.warnings : []);
      setGeneratedAt(data?.generated_at || null);
    } catch (fetchError) {
      setError(fetchError.message || '加载图表失败');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchPlots();
  }, [fetchPlots]);

  const sections = useMemo(() => buildSections(charts), [charts]);

  const warningCharts = useMemo(() => {
    const ids = new Set();
    warnings.forEach((warning) => {
      getWarningCharts(warning).forEach((chartId) => ids.add(chartId));
    });
    return ids;
  }, [warnings]);

  const navigationCharts = useMemo(() => {
    const orderedCharts = [];

    sections.forEach((section) => {
      section.leadCharts.forEach((chart) => orderedCharts.push(chart));
      section.supportCharts.forEach((chart) => orderedCharts.push(chart));
    });

    return orderedCharts;
  }, [sections]);

  const sectionCount = sections.length;
  const warningCount = warnings.length;
  const generatedText = formatGeneratedAt(generatedAt);

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
        background: 'linear-gradient(180deg, #faf8f1 0%, #eef5f1 46%, #edf2ef 100%)',
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
            background:
              'linear-gradient(145deg, rgba(255, 255, 255, 0.88) 0%, rgba(246, 250, 247, 0.82) 44%, rgba(239, 246, 242, 0.92) 100%)',
            border: '1px solid rgba(16, 35, 28, 0.08)',
            boxShadow: '0 28px 70px rgba(11, 27, 21, 0.1)',
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
                  background: 'rgba(70, 161, 125, 0.1)',
                  color: '#2e7258',
                  fontSize: 12,
                  fontWeight: 700,
                  width: 'fit-content',
                  letterSpacing: '0.03em',
                }}
              >
                <LineChart size={14} />
                plots dashboard
              </div>
              <div style={{ display: 'grid', gap: 8 }}>
                <h1
                  style={{
                    margin: 0,
                    fontSize: 'clamp(34px, 4vw, 52px)',
                    lineHeight: 1,
                    letterSpacing: '-0.05em',
                    color: '#10231c',
                  }}
                >
                  先看最影响健康的图，再看辅助分析图
                </h1>
                <p
                  style={{
                    margin: 0,
                    fontSize: 15,
                    lineHeight: 1.75,
                    color: 'rgba(16, 35, 28, 0.7)',
                    maxWidth: 760,
                  }}
                >
                  这个页面现在按信息优先级重排：顶部先给总览与异常提示，中段放体重和时间配置主图，下段再放训练、HHH 和财务。
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
                  ? 'rgba(19, 45, 37, 0.2)'
                  : 'linear-gradient(135deg, #173328 0%, #285845 100%)',
                color: '#f8fcfa',
                fontSize: 13,
                fontWeight: 700,
                boxShadow: isRefreshing ? 'none' : '0 18px 36px rgba(18, 43, 34, 0.18)',
              }}
            >
              <RefreshCw size={15} />
              {isRefreshing ? '刷新中...' : 'Refresh charts'}
            </button>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            <SummaryPill label="图表数量" value={`${charts.length}`} />
            <SummaryPill label="分组数量" value={`${sectionCount}`} />
            <SummaryPill label="警告数量" value={`${warningCount}`} tone={warningCount ? 'warning' : 'default'} />
            <SummaryPill label="最近生成" value={generatedText} />
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
                    background: warningCharts.has(chart.id) ? 'rgba(255, 241, 213, 0.92)' : 'rgba(255, 255, 255, 0.74)',
                    color: warningCharts.has(chart.id) ? '#8f5600' : '#244739',
                    fontSize: 12,
                    fontWeight: 700,
                    boxShadow: 'inset 0 0 0 1px rgba(16, 35, 28, 0.08)',
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
              background: 'rgba(255, 236, 236, 0.86)',
              border: '1px solid rgba(164, 63, 63, 0.16)',
              color: '#7b2c2c',
            }}
          >
            <div style={{ fontWeight: 700 }}>图表加载失败</div>
            <div style={{ marginTop: 6, fontSize: 14 }}>{error}</div>
          </section>
        ) : null}

        <WarningPanel warnings={warnings} onSelectChart={scrollToChart} />

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
                  background:
                    'linear-gradient(135deg, rgba(255, 255, 255, 0.76) 0%, rgba(240, 246, 242, 0.9) 100%)',
                  border: '1px solid rgba(16, 35, 28, 0.06)',
                }}
              />
            ))}
          </section>
        ) : null}

        {!isLoading && !charts.length ? (
          <section
            style={{
              padding: 32,
              borderRadius: 28,
              background: 'rgba(255, 255, 255, 0.78)',
              border: '1px solid rgba(16, 35, 28, 0.08)',
              color: '#173328',
            }}
          >
            暂无可显示的图表数据。
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
              />
            ))}
          </main>
        ) : null}
      </div>
    </div>
  );
}

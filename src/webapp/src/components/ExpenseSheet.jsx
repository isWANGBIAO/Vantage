import { useEffect, useMemo, useState } from 'react';
import {
  BarChart3,
  ClipboardList,
  Coins,
  Clock,
  HandCoins,
  RefreshCw,
  TableProperties,
  TrendingUp,
  Wallet,
} from 'lucide-react';
import { fetchBackend } from '../utils/backendRequest';
import './ExpenseSheet.css';
import { buildExpenseSheetViewModel } from './expenseSheetModel.js';
import {
  buildExpenseTrendChartModel,
  filterTrendPoints,
} from './expenseTrendChart.js';

const chartDimensions = { width: 960, height: 320 };
const trendRangeOptions = [
  { id: '6m', label: '6个月' },
  { id: '1y', label: '1年' },
  { id: 'all', label: '全部' },
];
const kpiHints = {
  cashAndStock: '以当前可见时间窗的最新资产为准',
  dailyBurn: '按程序运行时刻倒推到最近有效记录',
  requiredBudget: '从预算表汇总，不受未来开销行影响',
  coverageDays: '按最新资产和最近日均支出估算',
};

const formatNumber = (value, digits = 2) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  if (typeof value === 'number') {
    return value.toLocaleString('zh-CN', { maximumFractionDigits: digits });
  }
  return value;
};

const formatCurrency = (value) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `¥${formatNumber(value, 2)}`;
};

const formatDays = (value) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `${formatNumber(value, 1)} 天`;
};

const formatSignedCurrency = (value) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const sign = value > 0 ? '+' : value < 0 ? '-' : '';
  return `${sign}${formatCurrency(Math.abs(value))}`;
};

function formatMetricValue(item) {
  if (item.unit === 'currency') return formatCurrency(item.value);
  if (item.unit === 'days') return formatDays(item.value);
  return formatNumber(item.value);
}

function SectionHeader({ icon, title, description }) {
  const IconComponent = icon;

  return (
    <div className="expense-section-header">
      <div className="expense-section-heading">
        <span className="expense-section-icon">
          <IconComponent size={16} />
        </span>
        <div>
          <h3>{title}</h3>
          {description ? <p>{description}</p> : null}
        </div>
      </div>
    </div>
  );
}

function MetricRow({ label, value, hint }) {
  return (
    <div className="expense-metric-row">
      <span>{label}</span>
      <strong>{value}</strong>
      {hint ? <span className="expense-metric-hint">{hint}</span> : null}
    </div>
  );
}

function SheetTable({ sheet }) {
  return (
    <div className="expense-raw-sheet">
      <div className="expense-raw-sheet-header">
        <div>
          <h3>{sheet.name}</h3>
          <p>
            共 {sheet.row_count} 行{sheet.truncated ? '（已截断）' : ''}
          </p>
        </div>
      </div>
      <div className="expense-table-scroll">
        <table className="expense-table">
          <thead>
            <tr>
              {sheet.columns.map((col, idx) => (
                <th key={idx}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sheet.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex}>
                    {cell === null || cell === undefined || cell === '' ? '--' : String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TrendLegendItem({ color, label }) {
  return (
    <div className="expense-trend-legend-item">
      <span className="expense-trend-legend-swatch" style={{ background: color }} />
      <span>{label}</span>
    </div>
  );
}

function TrendStat({ label, value, hint }) {
  return (
    <div className="expense-trend-stat">
      <span className="expense-trend-stat-label">{label}</span>
      <strong className="expense-trend-stat-value">{value}</strong>
      {hint ? <span className="expense-trend-stat-hint">{hint}</span> : null}
    </div>
  );
}

function TrendChartSvg({ model }) {
  const latestBalancePoint = model.balancePoints.at(-1) || null;
  const latestSpendPoint = model.spendPoints.at(-1) || null;

  return (
    <svg
      className="expense-trend-svg"
      viewBox={`0 0 ${chartDimensions.width} ${chartDimensions.height}`}
      role="img"
      aria-label="资产与支出趋势图"
    >
      <defs>
        <linearGradient id="expense-balance-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgba(116, 185, 255, 0.28)" />
          <stop offset="100%" stopColor="rgba(116, 185, 255, 0)" />
        </linearGradient>
      </defs>

      <rect
        x="0"
        y="0"
        width={chartDimensions.width}
        height={chartDimensions.height}
        rx="18"
        fill="rgba(4, 9, 18, 0.94)"
      />

      {model.balanceTicks.map((tick, index) => (
        <g key={`balance-grid-${index}`}>
          <line
            x1={model.chartLeft}
            y1={tick.y}
            x2={model.chartRight}
            y2={tick.y}
            stroke="rgba(255,255,255,0.08)"
            strokeDasharray="6 10"
          />
          <text
            x={model.chartLeft - 14}
            y={tick.y + 4}
            textAnchor="end"
            fontSize="12"
            fill="rgba(116,185,255,0.82)"
          >
            {tick.label}
          </text>
        </g>
      ))}

      {model.xTicks.map((tick) => (
        <g key={`x-${tick.label}-${tick.x}`}>
          <line
            x1={tick.x}
            y1={model.chartTop}
            x2={tick.x}
            y2={model.chartBottom}
            stroke="rgba(255,255,255,0.05)"
          />
          <text
            x={tick.x}
            y={chartDimensions.height - 16}
            textAnchor="middle"
            fontSize="12"
            fill="rgba(255,255,255,0.66)"
          >
            {tick.label}
          </text>
        </g>
      ))}

      {model.spendTicks.map((tick, index) => (
        <text
          key={`spend-tick-${index}`}
          x={model.chartRight + 14}
          y={tick.y + 4}
          textAnchor="start"
          fontSize="12"
          fill="rgba(255,180,99,0.82)"
        >
          {tick.label}
        </text>
      ))}

      {model.balanceAreaPath ? (
        <path d={model.balanceAreaPath} fill="url(#expense-balance-fill)" />
      ) : null}
      {model.balancePath ? (
        <path
          d={model.balancePath}
          fill="none"
          stroke="#74b9ff"
          strokeWidth="4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ) : null}
      {model.spendPath ? (
        <path
          d={model.spendPath}
          fill="none"
          stroke="#ffb463"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ) : null}

      {latestBalancePoint ? (
        <circle cx={latestBalancePoint.x} cy={latestBalancePoint.y} r="5.5" fill="#74b9ff" />
      ) : null}
      {latestSpendPoint ? (
        <circle cx={latestSpendPoint.x} cy={latestSpendPoint.y} r="5" fill="#ffb463" />
      ) : null}

      <text
        x={model.chartLeft}
        y={18}
        fontSize="12"
        fill="rgba(116,185,255,0.82)"
      >
        现金及现金等价物+股票
      </text>
      <text
        x={model.chartRight}
        y={18}
        textAnchor="end"
        fontSize="12"
        fill="rgba(255,180,99,0.82)"
      >
        日均支出
      </text>
    </svg>
  );
}

function BalanceTrendCard({ trendChart, activeRange, onRangeChange }) {
  const availableRanges = useMemo(
    () => trendRangeOptions.filter((item) => item.id === 'all' || filterTrendPoints(trendChart.points, item.id).length > 1),
    [trendChart.points],
  );

  const filteredPoints = useMemo(
    () => filterTrendPoints(trendChart.points, activeRange),
    [activeRange, trendChart.points],
  );

  const model = useMemo(
    () => buildExpenseTrendChartModel({ points: filteredPoints, ...chartDimensions }),
    [filteredPoints],
  );

  return (
    <section className="glass-panel expense-trend-card">
      <div className="expense-trend-head">
        <div className="expense-section-heading">
          <span className="expense-section-icon">
            <TrendingUp size={16} />
          </span>
          <div>
            <h3>资产与支出趋势</h3>
            <p>把资产曲线放回 Expense Sheet 主视图，保留趋势、变化和原始表格三层信息。</p>
          </div>
        </div>

        <div className="expense-trend-range-list" role="tablist" aria-label="Chart range">
          {availableRanges.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`expense-trend-range-button ${activeRange === item.id ? 'is-active' : ''}`}
              onClick={() => onRangeChange(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="expense-trend-metrics">
        <TrendStat label="最新资产" value={formatCurrency(trendChart.summary.latestBalance)} />
        <TrendStat label="最新日均支出" value={formatCurrency(trendChart.summary.latestDailyAverage)} />
        <TrendStat
          label="区间资产变化"
          value={formatSignedCurrency(trendChart.summary.balanceChange)}
          hint="基于当前可见时间窗首尾差值"
        />
        <TrendStat
          label="当前覆盖天数"
          value={formatDays(trendChart.summary.coverageDays)}
          hint={`最近记录 ${trendChart.summary.latestDate}`}
        />
      </div>

      <div className="expense-trend-shell">
        {filteredPoints.length ? (
          <TrendChartSvg model={model} />
        ) : (
          <div className="expense-trend-empty">当前还没有可绘制的资产趋势数据。</div>
        )}
      </div>

      <div className="expense-trend-footer">
        <div className="expense-trend-legend">
          <TrendLegendItem color="#74b9ff" label="现金及现金等价物+股票" />
          <TrendLegendItem color="#ffb463" label="日均支出" />
        </div>
        <span className="expense-trend-caption">参考仪表盘常见布局，把核心时间序列放在 KPI 与明细之间。</span>
      </div>
    </section>
  );
}

export default function ExpenseSheet() {
  const [data, setData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [activeRawSheet, setActiveRawSheet] = useState('');
  const [activeTrendRange, setActiveTrendRange] = useState('all');

  const fetchData = async () => {
    setIsLoading(true);
    setError('');

    try {
      const res = await fetchBackend('/api/balance_sheet', {
        retryPolicy: 'load',
        allowHttpError: true,
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || '加载开销表失败');
      }

      const payload = await res.json();
      setData(payload);
    } catch (err) {
      setError(err.message || '加载失败');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    void fetchData();
  }, []);

  const viewModel = useMemo(() => buildExpenseSheetViewModel(data), [data]);

  useEffect(() => {
    if (!activeRawSheet || !viewModel.rawSheets.some((sheet) => sheet.name === activeRawSheet)) {
      setActiveRawSheet(viewModel.defaultRawSheetName);
    }
  }, [activeRawSheet, viewModel.defaultRawSheetName, viewModel.rawSheets]);

  useEffect(() => {
    setActiveTrendRange(viewModel.trendChart.defaultRange);
  }, [viewModel.trendChart.defaultRange]);

  const handleRefresh = () => {
    setIsRefreshing(true);
    void fetchData();
  };

  const selectedRawSheet =
    viewModel.rawSheets.find((sheet) => sheet.name === activeRawSheet) || viewModel.rawSheets[0] || null;

  return (
    <div className="expense-sheet">
      <section className="glass-panel expense-toolbar">
        <div className="expense-toolbar-copy">
          <div className="expense-toolbar-title">
            <Wallet size={20} />
            <h2>开销表</h2>
          </div>
          <div className="expense-toolbar-meta">
            <span>
              <strong>文件</strong>
              {viewModel.meta.fileName}
            </span>
            <span title={viewModel.meta.fullPath}>
              <strong>来源</strong>
              {viewModel.meta.fullPath || 'Balance Sheet.xlsx'}
            </span>
            <span>
              <strong>更新</strong>
              {viewModel.meta.updatedAt}
            </span>
            <span>
              <strong>Sheet</strong>
              {viewModel.meta.sheetCount}
            </span>
          </div>
        </div>

        <button className="expense-refresh-button" onClick={handleRefresh} disabled={isRefreshing}>
          <RefreshCw size={16} className={isRefreshing ? 'spin-animation' : ''} />
          {isRefreshing ? '刷新中…' : '刷新'}
        </button>
      </section>

      {isLoading ? (
        <div className="glass-panel expense-state-panel">正在加载开销数据…</div>
      ) : null}

      {!isLoading && error ? (
        <div className="glass-panel expense-state-panel expense-error-panel">{error}</div>
      ) : null}

      {!isLoading && !error ? (
        <>
          <section className="glass-panel expense-kpi-strip">
            <div className="expense-kpi-strip-head">
              <div>
                <span className="expense-kpi-strip-eyebrow">Snapshot</span>
                <h3>当前财务快照</h3>
              </div>
              <p>上面的数字只取程序运行时之前的最近有效记录，给下面趋势卡做摘要入口。</p>
            </div>

            <div className="expense-kpi-strip-grid">
              {viewModel.kpis.map((item) => (
                <div key={item.id} className={`expense-kpi expense-kpi--${item.id}`}>
                  <span className="expense-kpi-label">{item.label}</span>
                  <strong className="expense-kpi-value">{formatMetricValue(item)}</strong>
                  <span className="expense-kpi-hint">{kpiHints[item.id]}</span>
                </div>
              ))}
            </div>
          </section>

          <BalanceTrendCard
            trendChart={viewModel.trendChart}
            activeRange={activeTrendRange}
            onRangeChange={setActiveTrendRange}
          />

          <div className="expense-workspace">
            <div className="expense-primary-column">
              <section className="glass-panel expense-section">
                <SectionHeader
                  icon={Clock}
                  title="近期开销"
                  description="优先显示最近有支出、备注或报销说明的记录。"
                />
                {viewModel.recentSpending.length ? (
                  <div className="expense-ledger-list">
                    {viewModel.recentSpending.map((item) => (
                      <article key={`${item.date}-${item.note}-${item.incomeNote}`} className="expense-ledger-item">
                        <div className="expense-ledger-topline">
                          <strong>{item.date}</strong>
                          <div className="expense-ledger-values">
                            <span>期间支出 {formatCurrency(item.periodSpend)}</span>
                            <span>日均 {formatCurrency(item.dailyAverage)}</span>
                          </div>
                        </div>
                        {item.note ? <p>大支出：{item.note}</p> : null}
                        {item.incomeNote ? <p>收入说明：{item.incomeNote}</p> : null}
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="expense-empty-copy">最近没有可展示的开销记录。</p>
                )}
              </section>

              <section className="glass-panel expense-section">
                <SectionHeader
                  icon={ClipboardList}
                  title="预算结构"
                  description="把固定预算和弹性预算拆开看，再按类别汇总。"
                />
                <div className="expense-budget-summary">
                  <MetricRow label="每月必须" value={formatCurrency(viewModel.budget.monthlyRequired)} />
                  <MetricRow label="每月弹性" value={formatCurrency(viewModel.budget.monthlyOptional)} />
                </div>
                {viewModel.budget.groups.length ? (
                  <div className="expense-budget-groups">
                    {viewModel.budget.groups.map((group) => (
                      <section key={group.name} className="expense-budget-group">
                        <div className="expense-budget-group-head">
                          <strong>{group.name}</strong>
                          <span>{formatCurrency(group.total)} / 月</span>
                        </div>
                        <div className="expense-budget-items">
                          {group.items.slice(0, 4).map((item) => (
                            <div key={`${group.name}-${item.name}`} className="expense-budget-item">
                              <span>{item.name}</span>
                              <span>{formatCurrency(item.monthlyValue)}</span>
                            </div>
                          ))}
                        </div>
                      </section>
                    ))}
                  </div>
                ) : (
                  <p className="expense-empty-copy">预算表里还没有可用的预算项目。</p>
                )}
              </section>
            </div>

            <aside className="expense-secondary-column">
              <section className="glass-panel expense-section">
                <SectionHeader
                  icon={Coins}
                  title="高值资产"
                  description="保留大于 1000 元的资产条目，更适合看清单而不是财务分类。"
                />
                {viewModel.assets.items.length ? (
                  <div className="expense-asset-list">
                    {viewModel.assets.items.map((item) => (
                      <div key={item.name} className="expense-asset-item">
                        <div>
                          <strong>{item.name}</strong>
                          <p>
                            数量 {formatNumber(item.quantity, 0)} · 单价 {formatCurrency(item.unitPrice)}
                          </p>
                        </div>
                        <span>{formatCurrency(item.totalPrice)}</span>
                      </div>
                    ))}
                    <div className="expense-asset-total">
                      <span>合计</span>
                      <strong>{formatCurrency(viewModel.assets.totalValue)}</strong>
                    </div>
                  </div>
                ) : (
                  <p className="expense-empty-copy">资产表里还没有高值资产记录。</p>
                )}
              </section>

              <section className="glass-panel expense-section">
                <SectionHeader
                  icon={HandCoins}
                  title="人情支出"
                  description="这部分是事件型支出，用紧凑列表比完整表格更合适。"
                />
                {viewModel.socialEvents.items.length ? (
                  <div className="expense-social-list">
                    {viewModel.socialEvents.items.map((item) => (
                      <div key={`${item.date}-${item.title}`} className="expense-social-item">
                        <div>
                          <strong>{item.title}</strong>
                          <p>{item.date || '未记录日期'}</p>
                        </div>
                        <span>{formatCurrency(item.amount)}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="expense-empty-copy">暂无人情记录。</p>
                )}
              </section>

              <section className="glass-panel expense-section">
                <SectionHeader
                  icon={BarChart3}
                  title="支出提示"
                  description="保留建议，但把它降级成辅助信息，不和核心指标抢位置。"
                />
                {(data?.suggestions || []).length ? (
                  <ul className="expense-suggestion-list">
                    {data.suggestions.map((item, idx) => (
                      <li key={idx}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="expense-empty-copy">当前没有额外提示。</p>
                )}
              </section>
            </aside>
          </div>

          <section className="glass-panel expense-section">
            <SectionHeader
              icon={TableProperties}
              title="原始工作表"
              description="原始表格保留为详情视图，一次只看一个 sheet。"
            />
            <div className="expense-tab-list" role="tablist" aria-label="Raw workbook sheets">
              {viewModel.rawSheets.map((sheet) => {
                const isActive = sheet.name === selectedRawSheet?.name;
                return (
                  <button
                    key={sheet.name}
                    type="button"
                    className={`expense-tab-button ${isActive ? 'is-active' : ''}`}
                    onClick={() => setActiveRawSheet(sheet.name)}
                  >
                    {sheet.name}
                  </button>
                );
              })}
            </div>
            {selectedRawSheet ? <SheetTable sheet={selectedRawSheet} /> : null}
          </section>
        </>
      ) : null}
    </div>
  );
}

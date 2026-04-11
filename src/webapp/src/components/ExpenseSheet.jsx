import { useEffect, useMemo, useState } from 'react';
import {
  BarChart3,
  ClipboardList,
  Coins,
  Clock,
  HandCoins,
  RefreshCw,
  TableProperties,
  Wallet,
} from 'lucide-react';
import { fetchBackend } from '../utils/backendRequest';
import './ExpenseSheet.css';
import { buildExpenseSheetViewModel } from './expenseSheetModel.js';

const formatNumber = (value, digits = 2) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  if (typeof value === 'number') {
    return value.toLocaleString('zh-CN', { maximumFractionDigits: digits });
  }
  return value;
};

const formatCurrency = (value) => formatNumber(value, 2);
const formatDays = (value) => (value === null || value === undefined ? '--' : `${formatNumber(value, 1)} 天`);

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

export default function ExpenseSheet() {
  const [data, setData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [activeRawSheet, setActiveRawSheet] = useState('');

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
    fetchData();
  }, []);

  const viewModel = useMemo(() => buildExpenseSheetViewModel(data), [data]);

  useEffect(() => {
    if (!activeRawSheet || !viewModel.rawSheets.some((sheet) => sheet.name === activeRawSheet)) {
      setActiveRawSheet(viewModel.defaultRawSheetName);
    }
  }, [activeRawSheet, viewModel.defaultRawSheetName, viewModel.rawSheets]);

  const handleRefresh = () => {
    setIsRefreshing(true);
    fetchData();
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
          {isRefreshing ? '刷新中...' : '刷新'}
        </button>
      </section>

      {isLoading ? (
        <div className="glass-panel expense-state-panel">正在加载开销数据...</div>
      ) : null}

      {!isLoading && error ? (
        <div className="glass-panel expense-state-panel expense-error-panel">{error}</div>
      ) : null}

      {!isLoading && !error ? (
        <>
          <section className="glass-panel expense-kpi-strip">
            {viewModel.kpis.map((item) => (
              <div key={item.id} className="expense-kpi">
                <span className="expense-kpi-label">{item.label}</span>
                <strong className="expense-kpi-value">{formatMetricValue(item)}</strong>
              </div>
            ))}
          </section>

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
                  description="保留建议，但把它降级为辅助信息，不和核心指标抢位置。"
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

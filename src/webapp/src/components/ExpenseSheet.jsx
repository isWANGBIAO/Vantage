import { useCallback, useEffect, useMemo, useState } from 'react';
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
import { fetchBackend, fetchBackendJson } from '../utils/backendRequest';
import './ExpenseSheet.css';
import { buildExpenseSheetViewModel } from './expenseSheetModel.js';
import PlotChartCard from './PlotChartCard.jsx';
import { useDisplayLanguage } from '../context/DisplayLanguageContext.jsx';
import { localizeExpenseSuggestion } from '../utils/expenseLocalization.js';

const KPI_HINT_KEYS = {
  cashAndStock: 'expense.kpi_hint.cash_and_stock',
  dailyBurn: 'expense.kpi_hint.daily_burn',
  requiredBudget: 'expense.kpi_hint.required_budget',
  coverageDays: 'expense.kpi_hint.coverage_days',
};

const KPI_LABEL_KEYS = {
  cashAndStock: 'expense.kpi.cash_and_stock',
  dailyBurn: 'expense.kpi.daily_burn',
  requiredBudget: 'expense.kpi.required_budget',
  coverageDays: 'expense.kpi.coverage_days',
};

function formatNumber(value, locale, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  if (typeof value === 'number') {
    return value.toLocaleString(locale, { maximumFractionDigits: digits });
  }
  return value;
}

function formatCurrency(value, locale) {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: 'CNY',
    maximumFractionDigits: 2,
  }).format(value);
}

function formatDays(value, locale, t) {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return t('expense.days_value', { value: formatNumber(value, locale, 1) });
}

function formatMetricValue(item, locale, t) {
  if (item.unit === 'currency') return formatCurrency(item.value, locale);
  if (item.unit === 'days') return formatDays(item.value, locale, t);
  return formatNumber(item.value, locale);
}

function compactWorkbookPath(fullPath) {
  const value = String(fullPath || '').trim();
  if (!value) return '';
  const parts = value.split(/[\\/]/).filter(Boolean);
  return parts.slice(-2).join(' / ') || value;
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

function SheetTable({ sheet, t }) {
  return (
    <div
      className="expense-raw-sheet"
      role="tabpanel"
      id={`expense-raw-sheet-${sheet.name}`}
      aria-labelledby={`expense-raw-tab-${sheet.name}`}
    >
      <div className="expense-raw-sheet-header">
        <div>
          <h3>{sheet.name}</h3>
          <p>{t('expense.raw_sheet_rows', {
            count: sheet.row_count,
            suffix: sheet.truncated ? t('expense.raw_sheet_truncated') : '',
          })}</p>
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

export default function ExpenseSheet({ theme = 'dark' }) {
  const { effectiveLanguage, t } = useDisplayLanguage();
  const [data, setData] = useState(null);
  const [balanceChart, setBalanceChart] = useState(null);
  const [balanceChartError, setBalanceChartError] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [activeRawSheet, setActiveRawSheet] = useState('');

  const fetchData = useCallback(async (refresh = false) => {
    setIsLoading(true);
    setError('');
    setBalanceChartError('');

    try {
      if (refresh) {
        await fetchBackendJson('/api/plots/refresh', {
          method: 'POST',
          retryPolicy: 'mutation',
        });
      }

      const plotsPromise = fetchBackendJson('/api/plots/data')
        .then((payload) => ({ ok: true, payload }))
        .catch((err) => ({ ok: false, error: err.message || t('expense.error.load_chart') }));

      const [res, plotResult] = await Promise.all([
        fetchBackend('/api/balance_sheet', {
          retryPolicy: 'load',
          allowHttpError: true,
        }),
        plotsPromise,
      ]);

      if (!res.ok) {
        const payload = await res.json();
        throw new Error(payload.error || t('expense.error.load_sheet'));
      }

      const payload = await res.json();
      setData(payload);

      if (plotResult.ok) {
        const nextChart = Array.isArray(plotResult.payload?.charts)
          ? plotResult.payload.charts.find((item) => item.id === 'balance') || null
          : null;

        setBalanceChart(nextChart);
        setBalanceChartError(nextChart ? '' : t('expense.error.chart_not_found'));
      } else {
        setBalanceChart(null);
        setBalanceChartError(plotResult.error);
      }
    } catch (err) {
      setBalanceChart(null);
      setError(err.message || t('expense.error.generic'));
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [t]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const viewModel = useMemo(() => buildExpenseSheetViewModel(data), [data]);

  useEffect(() => {
    if (!activeRawSheet || !viewModel.rawSheets.some((sheet) => sheet.name === activeRawSheet)) {
      setActiveRawSheet(viewModel.defaultRawSheetName);
    }
  }, [activeRawSheet, viewModel.defaultRawSheetName, viewModel.rawSheets]);

  const handleRefresh = () => {
    setIsRefreshing(true);
    void fetchData(true);
  };

  const selectedRawSheet =
    viewModel.rawSheets.find((sheet) => sheet.name === activeRawSheet) || viewModel.rawSheets[0] || null;
  const compactSourcePath = compactWorkbookPath(viewModel.meta.fullPath);

  const balanceChartCard = balanceChart || {
    id: 'balance',
    title: t('expense.balance_chart_title'),
    description: t('expense.balance_chart_description'),
    empty: true,
    message: balanceChartError || t('expense.balance_chart_unavailable'),
    height: 430,
    summary: [],
  };

  return (
    <div className="expense-sheet">
      <section className="glass-panel expense-toolbar">
        <div className="expense-toolbar-copy">
          <div className="expense-toolbar-title">
            <Wallet size={20} />
            <h2>{t('expense.title')}</h2>
          </div>
          <div className="expense-toolbar-meta">
            <span>
              <strong>{t('expense.file')}</strong>
              {viewModel.meta.fileName}
            </span>
            <span title={viewModel.meta.fullPath}>
              <strong>{t('expense.source')}</strong>
              {compactSourcePath || t('expense.file_fallback')}
            </span>
            <span>
              <strong>{t('expense.updated')}</strong>
              {viewModel.meta.updatedAt}
            </span>
            <span>
              <strong>{t('expense.sheets')}</strong>
              {viewModel.meta.sheetCount}
            </span>
          </div>
        </div>

        <button className="expense-refresh-button" onClick={handleRefresh} disabled={isRefreshing}>
          <RefreshCw size={16} className={isRefreshing ? 'spin-animation' : ''} />
          {isRefreshing ? t('expense.refreshing') : t('expense.refresh')}
        </button>
      </section>

      {isLoading ? (
        <div className="glass-panel expense-state-panel">{t('expense.loading')}</div>
      ) : null}

      {!isLoading && error ? (
        <div className="glass-panel expense-state-panel expense-error-panel">{error}</div>
      ) : null}

      {!isLoading && !error ? (
        <>
          <section className="glass-panel expense-kpi-strip">
            <div className="expense-kpi-strip-head">
              <div>
                <span className="expense-kpi-strip-eyebrow">{t('expense.snapshot_kicker')}</span>
                <h3>{t('expense.snapshot_title')}</h3>
              </div>
              <p>{t('expense.snapshot_description')}</p>
            </div>

            <div className="expense-kpi-strip-grid">
              {viewModel.kpis.map((item) => (
                <div key={item.id} className={`expense-kpi expense-kpi--${item.id}`}>
                  <span className="expense-kpi-label">{t(KPI_LABEL_KEYS[item.id])}</span>
                  <strong className="expense-kpi-value">{formatMetricValue(item, effectiveLanguage, t)}</strong>
                  <span className="expense-kpi-hint">{t(KPI_HINT_KEYS[item.id])}</span>
                </div>
              ))}
            </div>
          </section>

          <PlotChartCard
            chart={balanceChartCard}
            accent="#f59f54"
            featured
            eyebrow={t('expense.chart_eyebrow')}
            chartHeight={430}
            theme={theme}
          />

          <div className="expense-workspace">
            <div className="expense-primary-column">
              <section className="glass-panel expense-section">
                <SectionHeader
                  icon={Clock}
                  title={t('expense.recent_spending')}
                  description={t('expense.recent_spending_desc')}
                />
                {viewModel.recentSpending.length ? (
                  <div className="expense-ledger-list">
                    {viewModel.recentSpending.map((item) => (
                      <article key={`${item.date}-${item.note}-${item.incomeNote}`} className="expense-ledger-item">
                        <div className="expense-ledger-topline">
                          <strong>{item.date}</strong>
                          <div className="expense-ledger-values">
                            <span>{t('expense.period_spend', { value: formatCurrency(item.periodSpend, effectiveLanguage) })}</span>
                            <span>{t('expense.daily_average', { value: formatCurrency(item.dailyAverage, effectiveLanguage) })}</span>
                          </div>
                        </div>
                        {item.note ? <p>{t('expense.large_spend', { value: item.note })}</p> : null}
                        {item.incomeNote ? <p>{t('expense.income_note', { value: item.incomeNote })}</p> : null}
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="expense-empty-copy">{t('expense.no_recent_spending')}</p>
                )}
              </section>

              <section className="glass-panel expense-section">
                <SectionHeader
                  icon={ClipboardList}
                  title={t('expense.budget_structure')}
                  description={t('expense.budget_structure_desc')}
                />
                <div className="expense-budget-summary">
                  <MetricRow label={t('expense.monthly_required')} value={formatCurrency(viewModel.budget.monthlyRequired, effectiveLanguage)} />
                  <MetricRow label={t('expense.monthly_optional')} value={formatCurrency(viewModel.budget.monthlyOptional, effectiveLanguage)} />
                </div>
                {viewModel.budget.groups.length ? (
                  <div className="expense-budget-groups">
                    {viewModel.budget.groups.map((group) => (
                      <section key={group.name} className="expense-budget-group">
                        <div className="expense-budget-group-head">
                          <strong>{group.name}</strong>
                          <span>{formatCurrency(group.total, effectiveLanguage)} {t('expense.per_month')}</span>
                        </div>
                        <div className="expense-budget-items">
                          {group.items.slice(0, 4).map((item) => (
                            <div key={`${group.name}-${item.name}`} className="expense-budget-item">
                              <span>{item.name}</span>
                              <span>{formatCurrency(item.monthlyValue, effectiveLanguage)}</span>
                            </div>
                          ))}
                          {group.items.length > 4 ? (
                            <div className="expense-budget-more">
                              {t('expense.more_items', { count: group.items.length - 4 })}
                            </div>
                          ) : null}
                        </div>
                      </section>
                    ))}
                  </div>
                ) : (
                  <p className="expense-empty-copy">{t('expense.no_budget')}</p>
                )}
              </section>
            </div>

            <aside className="expense-secondary-column">
              <section className="glass-panel expense-section">
                <SectionHeader
                  icon={Coins}
                  title={t('expense.high_value_assets')}
                  description={t('expense.high_value_assets_desc')}
                />
                {viewModel.assets.items.length ? (
                  <div className="expense-asset-list">
                    {viewModel.assets.items.map((item) => (
                      <div key={item.name} className="expense-asset-item">
                        <div>
                          <strong>{item.name}</strong>
                          <p>{t('expense.quantity_price', {
                            quantity: formatNumber(item.quantity, effectiveLanguage, 0),
                            price: formatCurrency(item.unitPrice, effectiveLanguage),
                          })}</p>
                        </div>
                        <span>{formatCurrency(item.totalPrice, effectiveLanguage)}</span>
                      </div>
                    ))}
                    <div className="expense-asset-total">
                      <span>{t('expense.total')}</span>
                      <strong>{formatCurrency(viewModel.assets.totalValue, effectiveLanguage)}</strong>
                    </div>
                  </div>
                ) : (
                  <p className="expense-empty-copy">{t('expense.no_assets')}</p>
                )}
              </section>

              <section className="glass-panel expense-section">
                <SectionHeader
                  icon={HandCoins}
                  title={t('expense.social')}
                  description={t('expense.social_desc')}
                />
                {viewModel.socialEvents.items.length ? (
                  <div className="expense-social-list">
                    {viewModel.socialEvents.items.map((item) => (
                      <div key={`${item.date}-${item.title}`} className="expense-social-item">
                        <div>
                          <strong>{item.title}</strong>
                          <p>{item.date || t('expense.no_date')}</p>
                        </div>
                        <span>{formatCurrency(item.amount, effectiveLanguage)}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="expense-empty-copy">{t('expense.no_social')}</p>
                )}
              </section>

              <section className="glass-panel expense-section">
                <SectionHeader
                  icon={BarChart3}
                  title={t('expense.tips')}
                  description={t('expense.tips_desc')}
                />
                {(data?.suggestions || []).length ? (
                  <ul className="expense-suggestion-list">
                    {data.suggestions.map((item, idx) => (
                      <li key={idx}>{localizeExpenseSuggestion(item, effectiveLanguage)}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="expense-empty-copy">{t('expense.no_tips')}</p>
                )}
              </section>
            </aside>
          </div>

          <section className="glass-panel expense-section">
            <SectionHeader
              icon={TableProperties}
              title={t('expense.raw_sheets')}
              description={t('expense.raw_sheets_desc')}
            />
            <div className="expense-tab-list" role="tablist" aria-label={t('expense.raw_sheets_aria')}>
              {viewModel.rawSheets.map((sheet) => {
                const isActive = sheet.name === selectedRawSheet?.name;
                return (
                  <button
                    key={sheet.name}
                    type="button"
                    role="tab"
                    aria-selected={isActive}
                    aria-controls={`expense-raw-sheet-${sheet.name}`}
                    id={`expense-raw-tab-${sheet.name}`}
                    className={`expense-tab-button ${isActive ? 'is-active' : ''}`}
                    onClick={() => setActiveRawSheet(sheet.name)}
                  >
                    {sheet.name}
                  </button>
                );
              })}
            </div>
            {selectedRawSheet ? <SheetTable sheet={selectedRawSheet} t={t} /> : null}
          </section>
        </>
      ) : null}
    </div>
  );
}

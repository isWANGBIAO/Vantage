import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  BarChart3,
  CalendarRange,
  ClipboardList,
  Coins,
  Copy,
  Clock,
  HandCoins,
  Image as ImageIcon,
  RefreshCw,
  Sparkles,
  TableProperties,
  Wallet,
  X,
} from 'lucide-react';
import { buildBackendUrl, fetchBackend, fetchBackendJson } from '../utils/backendRequest';
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

const COPY_FEEDBACK_DURATION_MS = 1500;

async function writeTextWithFallback(content) {
  if (!content) {
    return false;
  }

  if (
    globalThis.navigator?.clipboard
    && typeof globalThis.navigator.clipboard.writeText === 'function'
  ) {
    await globalThis.navigator.clipboard.writeText(content);
    return true;
  }

  const documentRef = globalThis.document;
  if (!documentRef?.createElement || !documentRef.body || typeof documentRef.execCommand !== 'function') {
    return false;
  }

  const textarea = documentRef.createElement('textarea');
  textarea.value = content;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  documentRef.body.appendChild(textarea);
  textarea.select();

  try {
    return documentRef.execCommand('copy');
  } finally {
    documentRef.body.removeChild(textarea);
  }
}

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

function formatDateTime(value, locale) {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString(locale, {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function compactWorkbookPath(fullPath) {
  const value = String(fullPath || '').trim();
  if (!value) return '';
  const parts = value.split(/[\\/]/).filter(Boolean);
  return parts.slice(-2).join(' / ') || value;
}

function normalizePurchaseItemName(value) {
  return String(value || '').trim().toLocaleLowerCase();
}

function removePurchaseItemFromGroups(groups, groupKey, itemName) {
  const targetName = normalizePurchaseItemName(itemName);
  return (groups || []).map((group) => {
    if (group.key !== groupKey || !targetName) {
      return group;
    }

    return {
      ...group,
      items: (group.items || []).filter((item) => normalizePurchaseItemName(item.name) !== targetName),
    };
  });
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
  const [copyJsonStatus, setCopyJsonStatus] = useState('idle');
  const [purchaseRecommendations, setPurchaseRecommendations] = useState(null);
  const [purchaseLoading, setPurchaseLoading] = useState(true);
  const [purchaseError, setPurchaseError] = useState('');
  const [purchaseGenerating, setPurchaseGenerating] = useState(false);
  const [purchaseCopyStatus, setPurchaseCopyStatus] = useState('idle');
  const [dismissedPurchaseCount, setDismissedPurchaseCount] = useState(0);
  const copyStatusResetRef = useRef(null);
  const purchaseCopyStatusResetRef = useRef(null);
  const purchaseCoverPollTimeoutRef = useRef(null);

  const fetchDismissedPurchaseItems = useCallback(async () => {
    try {
      const payload = await fetchBackendJson('/api/balance_sheet/purchase_recommendations/dismissed', {
        retryPolicy: 'load',
      });
      setDismissedPurchaseCount(Number(payload?.count) || 0);
    } catch {
      setDismissedPurchaseCount(0);
    }
  }, []);

  const fetchPurchaseRecommendations = useCallback(async ({ regenerate = false, silent = false } = {}) => {
    if (regenerate) {
      setPurchaseGenerating(true);
    } else if (!silent) {
      setPurchaseLoading(true);
    }
    setPurchaseError('');

    try {
      const payload = regenerate
        ? await fetchBackendJson('/api/balance_sheet/purchase_recommendations/regenerate', {
          method: 'POST',
          retryPolicy: 'mutation',
        })
        : await fetchBackendJson('/api/balance_sheet/purchase_recommendations', {
          retryPolicy: 'load',
        });
      if (payload?.status === 'error') {
        throw new Error(payload.details || payload.error || t('expense.error.generic'));
      }
      setPurchaseRecommendations(payload);
      setDismissedPurchaseCount(Number(payload?.dismissed_count) || 0);
    } catch (err) {
      setPurchaseError(err.message || t('expense.error.generic'));
    } finally {
      setPurchaseLoading(false);
      setPurchaseGenerating(false);
    }
  }, [t]);

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

  useEffect(() => {
    void fetchPurchaseRecommendations();
  }, [fetchPurchaseRecommendations]);

  useEffect(() => {
    void fetchDismissedPurchaseItems();
  }, [fetchDismissedPurchaseItems]);

  useEffect(() => {
    if (purchaseRecommendations?.cover_image?.status === 'generating' && !purchaseLoading && !purchaseError) {
      purchaseCoverPollTimeoutRef.current = setTimeout(() => {
        purchaseCoverPollTimeoutRef.current = null;
        void fetchPurchaseRecommendations({ silent: true });
      }, 5000);
      return () => {
        if (purchaseCoverPollTimeoutRef.current) {
          clearTimeout(purchaseCoverPollTimeoutRef.current);
          purchaseCoverPollTimeoutRef.current = null;
        }
      };
    }
    return undefined;
  }, [
    fetchPurchaseRecommendations,
    purchaseError,
    purchaseLoading,
    purchaseRecommendations?.cover_image?.status,
  ]);

  useEffect(() => () => {
    if (copyStatusResetRef.current) {
      clearTimeout(copyStatusResetRef.current);
    }
    if (purchaseCopyStatusResetRef.current) {
      clearTimeout(purchaseCopyStatusResetRef.current);
    }
    if (purchaseCoverPollTimeoutRef.current) {
      clearTimeout(purchaseCoverPollTimeoutRef.current);
    }
  }, []);

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

  const scheduleCopyStatusReset = useCallback(() => {
    if (copyStatusResetRef.current) {
      clearTimeout(copyStatusResetRef.current);
    }

    copyStatusResetRef.current = setTimeout(() => {
      setCopyJsonStatus('idle');
      copyStatusResetRef.current = null;
    }, COPY_FEEDBACK_DURATION_MS);
  }, []);

  const handleCopyJson = useCallback(async () => {
    if (!data?.prompt_payload) {
      setCopyJsonStatus('failed');
      scheduleCopyStatusReset();
      return;
    }

    try {
      const copied = await writeTextWithFallback(JSON.stringify(data.prompt_payload));
      setCopyJsonStatus(copied ? 'copied' : 'failed');
    } catch {
      setCopyJsonStatus('failed');
    }

    scheduleCopyStatusReset();
  }, [data, scheduleCopyStatusReset]);

  const schedulePurchaseCopyStatusReset = useCallback(() => {
    if (purchaseCopyStatusResetRef.current) {
      clearTimeout(purchaseCopyStatusResetRef.current);
    }

    purchaseCopyStatusResetRef.current = setTimeout(() => {
      setPurchaseCopyStatus('idle');
      purchaseCopyStatusResetRef.current = null;
    }, COPY_FEEDBACK_DURATION_MS);
  }, []);

  const handleCopyPurchaseJson = useCallback(async () => {
    if (!purchaseRecommendations) {
      setPurchaseCopyStatus('failed');
      schedulePurchaseCopyStatusReset();
      return;
    }

    try {
      const copied = await writeTextWithFallback(JSON.stringify(purchaseRecommendations));
      setPurchaseCopyStatus(copied ? 'copied' : 'failed');
    } catch {
      setPurchaseCopyStatus('failed');
    }
    schedulePurchaseCopyStatusReset();
  }, [purchaseRecommendations, schedulePurchaseCopyStatusReset]);

  const handleCopyCoverPrompt = useCallback(async () => {
    const prompt = purchaseRecommendations?.cover_image?.prompt;
    if (!prompt) {
      setPurchaseCopyStatus('failed');
      schedulePurchaseCopyStatusReset();
      return;
    }

    try {
      const copied = await writeTextWithFallback(prompt);
      setPurchaseCopyStatus(copied ? 'copied' : 'failed');
    } catch {
      setPurchaseCopyStatus('failed');
    }
    schedulePurchaseCopyStatusReset();
  }, [purchaseRecommendations, schedulePurchaseCopyStatusReset]);

  const handleDismissPurchaseItem = useCallback(async (groupKey, item) => {
    if (!purchaseRecommendations || !item?.name) {
      return;
    }

    try {
      const payload = await fetchBackendJson('/api/balance_sheet/purchase_recommendations/dismiss', {
        method: 'POST',
        retryPolicy: 'mutation',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cache_key: purchaseRecommendations.cache_key,
          group_key: groupKey,
          item,
        }),
      });
      const nextCount = Number(payload?.count ?? purchaseRecommendations.dismissed_count ?? dismissedPurchaseCount) || 0;
      setDismissedPurchaseCount(nextCount);
      setPurchaseRecommendations((current) => {
        if (!current) {
          return current;
        }
        return {
          ...current,
          dismissed_count: nextCount,
          recommendation_groups: removePurchaseItemFromGroups(
            current.recommendation_groups,
            groupKey,
            item.name,
          ),
        };
      });
    } catch (err) {
      setPurchaseError(err.message || t('expense.error.generic'));
    }
  }, [dismissedPurchaseCount, purchaseRecommendations, t]);

  const handleClearDismissedPurchaseItems = useCallback(async () => {
    try {
      await fetchBackendJson('/api/balance_sheet/purchase_recommendations/dismissed', {
        method: 'DELETE',
        retryPolicy: 'mutation',
      });
      setDismissedPurchaseCount(0);
      await fetchPurchaseRecommendations();
    } catch (err) {
      setPurchaseError(err.message || t('expense.error.generic'));
    }
  }, [fetchPurchaseRecommendations, t]);

  const selectedRawSheet =
    viewModel.rawSheets.find((sheet) => sheet.name === activeRawSheet) || viewModel.rawSheets[0] || null;
  const compactSourcePath = compactWorkbookPath(viewModel.meta.fullPath);
  const copyJsonLabel = copyJsonStatus === 'copied'
    ? t('expense.copy_json_copied')
    : copyJsonStatus === 'failed'
      ? t('expense.copy_json_failed')
      : t('expense.copy_json');
  const purchaseCopyLabel = purchaseCopyStatus === 'copied'
    ? t('expense.purchase.copied')
    : purchaseCopyStatus === 'failed'
      ? t('expense.purchase.copy_failed')
      : t('expense.purchase.copy_json');
  const coverPromptCopyLabel = purchaseCopyStatus === 'copied'
    ? t('expense.purchase.copied')
    : purchaseCopyStatus === 'failed'
      ? t('expense.purchase.copy_failed')
      : t('expense.purchase.copy_cover_prompt');
  const purchaseDismissedCount = Number(purchaseRecommendations?.dismissed_count ?? dismissedPurchaseCount) || 0;

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

        <div className="expense-toolbar-actions">
          <button
            type="button"
            className={`expense-copy-json-button ${copyJsonStatus === 'copied' ? 'is-copied' : ''}`.trim()}
            onClick={handleCopyJson}
            disabled={isLoading || !data?.prompt_payload}
            title={data?.prompt_payload ? t('expense.copy_json') : t('expense.copy_json_unavailable')}
          >
            <Copy size={16} />
            {copyJsonLabel}
          </button>

          <button className="expense-refresh-button" onClick={handleRefresh} disabled={isRefreshing}>
            <RefreshCw size={16} className={isRefreshing ? 'spin-animation' : ''} />
            {isRefreshing ? t('expense.refreshing') : t('expense.refresh')}
          </button>
        </div>
      </section>

      <section className="glass-panel expense-purchase-card">
        <div className="expense-purchase-head">
          <div className="expense-section-heading">
            <span className="expense-section-icon">
              <Sparkles size={16} />
            </span>
            <div>
              <h3>{t('expense.purchase.title')}</h3>
              <p>{t('expense.purchase.subtitle')}</p>
            </div>
          </div>
          <div className="expense-purchase-actions">
            <button
              type="button"
              className="secondary-button"
              onClick={handleCopyPurchaseJson}
              disabled={!purchaseRecommendations}
            >
              <Copy size={15} />
              {purchaseCopyLabel}
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={handleCopyCoverPrompt}
              disabled={!purchaseRecommendations?.cover_image?.prompt}
            >
              <Copy size={15} />
              {coverPromptCopyLabel}
            </button>
            <button
              type="button"
              className="expense-refresh-button"
              onClick={() => fetchPurchaseRecommendations({ regenerate: true })}
              disabled={purchaseGenerating}
            >
              <RefreshCw size={16} className={purchaseGenerating ? 'spin-animation' : ''} />
              {purchaseGenerating ? t('expense.purchase.generating') : t('expense.purchase.regenerate')}
            </button>
          </div>
        </div>

        {purchaseLoading ? (
          <div className="expense-purchase-state">{t('expense.purchase.loading')}</div>
        ) : null}

        {!purchaseLoading && purchaseError ? (
          <div className="expense-purchase-state expense-error-panel">
            {t('expense.purchase.error', { error: purchaseError })}
          </div>
        ) : null}

        {!purchaseLoading && !purchaseError && purchaseRecommendations ? (
          <div className="expense-purchase-body">
            <div className="expense-purchase-cover">
              {purchaseRecommendations.cover_image?.url ? (
                <img
                  src={buildBackendUrl(purchaseRecommendations.cover_image.url)}
                  alt={t('expense.purchase.title')}
                />
              ) : (
                <div className="expense-purchase-cover-empty">
                  <ImageIcon size={24} />
                  <span>
                    {purchaseRecommendations.cover_image?.status === 'generating'
                      ? t('expense.purchase.cover_generating')
                      : purchaseRecommendations.cover_image?.error || t('expense.purchase.cover_unavailable')}
                  </span>
                </div>
              )}
            </div>
            <div className="expense-purchase-content">
              <div className="expense-purchase-meta">
                <span>{purchaseRecommendations.from_cache ? t('expense.purchase.cached') : t('expense.purchase.fresh')}</span>
                <span>{t('expense.purchase.generated_at', {
                  value: formatDateTime(purchaseRecommendations.generated_at, effectiveLanguage),
                })}</span>
                {purchaseRecommendations.text_model ? (
                  <span>{t('expense.purchase.text_model', { value: purchaseRecommendations.text_model })}</span>
                ) : null}
                {purchaseRecommendations.image_model ? (
                  <span>{t('expense.purchase.image_model', { value: purchaseRecommendations.image_model })}</span>
                ) : null}
                <span>{t('expense.purchase.dismissed_count', { count: purchaseDismissedCount })}</span>
                <button
                  type="button"
                  className="expense-purchase-clear-dismissed"
                  onClick={handleClearDismissedPurchaseItems}
                  disabled={purchaseDismissedCount <= 0}
                  title={t('expense.purchase.clear_dismissed_title')}
                >
                  {t('expense.purchase.clear_dismissed')}
                </button>
              </div>
              <div className="expense-purchase-groups">
                {(purchaseRecommendations.recommendation_groups || []).map((group) => (
                  <section key={group.key} className="expense-purchase-group">
                    <h4>{group.title}</h4>
                    {group.items?.length ? (
                      <div className="expense-purchase-items">
                        {group.items.map((item) => (
                          <article key={`${group.key}-${item.name}`} className="expense-purchase-item">
                            <button
                              type="button"
                              className="expense-purchase-dismiss-button"
                              onClick={() => handleDismissPurchaseItem(group.key, item)}
                              title={t('expense.purchase.dismiss')}
                              aria-label={t('expense.purchase.dismiss')}
                            >
                              <X size={14} />
                            </button>
                            <div className="expense-purchase-item-head">
                              <strong>{item.name}</strong>
                              {item.category ? <span>{item.category}</span> : null}
                            </div>
                            {item.estimated_price ? (
                              <p><b>{t('expense.purchase.estimated_price')}:</b> {item.estimated_price}</p>
                            ) : null}
                            {item.reason ? <p>{item.reason}</p> : null}
                            {item.evidence ? (
                              <p><b>{t('expense.purchase.evidence')}:</b> {item.evidence}</p>
                            ) : null}
                            {item.duplicate_check ? (
                              <p><b>{t('expense.purchase.duplicate_check')}:</b> {item.duplicate_check}</p>
                            ) : null}
                            {item.impulse_risk ? (
                              <p><b>{t('expense.purchase.impulse_risk')}:</b> {item.impulse_risk}</p>
                            ) : null}
                          </article>
                        ))}
                      </div>
                    ) : (
                      <p className="expense-empty-copy">{t('expense.purchase.no_items')}</p>
                    )}
                  </section>
                ))}
              </div>
            </div>
          </div>
        ) : null}
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
                          {group.items.map((item) => (
                            <div key={`${group.name}-${item.name}`} className="expense-budget-item">
                              <span>{item.name}</span>
                              <span>{formatCurrency(item.monthlyValue, effectiveLanguage)}</span>
                            </div>
                          ))}
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
              {viewModel.forecast.monthCount > 0 ? (
                <section className="glass-panel expense-section">
                  <SectionHeader
                    icon={CalendarRange}
                    title={t('expense.forecast_title')}
                    description={t('expense.forecast_desc')}
                  />
                  <div className="expense-forecast-summary">
                    <MetricRow
                      label={t('expense.forecast_range')}
                      value={`${viewModel.forecast.startDate} - ${viewModel.forecast.endDate}`}
                      hint={t('expense.forecast_range_hint', {
                        count: formatNumber(viewModel.forecast.monthCount, effectiveLanguage, 0),
                      })}
                    />
                    <MetricRow
                      label={t('expense.forecast_fixed_income')}
                      value={formatCurrency(viewModel.forecast.monthlyFixedIncome, effectiveLanguage)}
                      hint={t('expense.forecast_fixed_income_hint')}
                    />
                    <MetricRow
                      label={t('expense.forecast_extra_income')}
                      value={formatCurrency(viewModel.forecast.monthlyExtraIncome, effectiveLanguage)}
                    />
                    <MetricRow
                      label={t('expense.forecast_total_income')}
                      value={formatCurrency(viewModel.forecast.monthlyTotalIncome, effectiveLanguage)}
                    />
                    <MetricRow
                      label={t('expense.forecast_planned_spend')}
                      value={formatCurrency(viewModel.forecast.monthlyPlannedSpend, effectiveLanguage)}
                    />
                    <MetricRow
                      label={t('expense.forecast_net_cash_flow')}
                      value={formatCurrency(viewModel.forecast.monthlyNetCashFlow, effectiveLanguage)}
                    />
                    <MetricRow
                      label={t('expense.forecast_projected_balance')}
                      value={formatCurrency(viewModel.forecast.latestProjectedBalance, effectiveLanguage)}
                    />
                  </div>
                </section>
              ) : null}

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

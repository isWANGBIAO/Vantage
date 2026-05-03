import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const jsxSource = readFileSync(new URL('./ExpenseSheet.jsx', import.meta.url), 'utf8');
const cssSource = readFileSync(new URL('./ExpenseSheet.css', import.meta.url), 'utf8');

test('Expense Sheet uses a compact snapshot structure for the top KPI strip', () => {
  assert.ok(jsxSource.includes('expense-kpi-strip-head'));
  assert.ok(jsxSource.includes('expense-kpi-strip-grid'));
  assert.ok(jsxSource.includes('expense-kpi-hint'));
  assert.ok(cssSource.includes('.expense-kpi-strip-head'));
  assert.ok(cssSource.includes('.expense-kpi-strip-grid'));
  assert.ok(cssSource.includes('.expense-kpi-hint'));
});

test('Expense Sheet pulls static UI copy from the display language layer', () => {
  assert.ok(jsxSource.includes("useDisplayLanguage()"));
  assert.ok(jsxSource.includes("t('expense.title')"));
  assert.ok(jsxSource.includes("t('expense.balance_chart_title')"));
  assert.ok(jsxSource.includes("t('expense.forecast_title')"));
  assert.ok(jsxSource.includes("t('expense.raw_sheets_aria')"));
});

test('Expense Sheet renders a separate future income forecast section', () => {
  assert.ok(jsxSource.includes('viewModel.forecast.monthCount > 0'));
  assert.ok(jsxSource.includes('expense-forecast-summary'));
  assert.ok(jsxSource.includes("viewModel.forecast.monthlyFixedIncome"));
  assert.ok(jsxSource.includes("viewModel.forecast.latestProjectedBalance"));
  assert.ok(cssSource.includes('.expense-forecast-summary'));
});

test('Expense Sheet refresh clears the dashboard cache before reloading charts', () => {
  assert.ok(jsxSource.includes("fetchBackendJson('/api/plots/refresh', {"));
  assert.ok(jsxSource.includes("method: 'POST'"));
  assert.ok(jsxSource.includes("retryPolicy: 'mutation'"));
  assert.ok(!jsxSource.includes("'/api/plots/data${refresh ? '?refresh=1' : ''}'"));
});

test('Expense Sheet provides a toolbar action for copying the full prompt JSON', () => {
  assert.ok(jsxSource.includes('Copy,'));
  assert.ok(jsxSource.includes("t('expense.copy_json')"));
  assert.ok(jsxSource.includes("t('expense.copy_json_copied')"));
  assert.ok(jsxSource.includes("data?.prompt_payload"));
  assert.ok(jsxSource.includes('JSON.stringify(data.prompt_payload)'));
  assert.ok(jsxSource.includes('writeTextWithFallback'));
  assert.ok(jsxSource.includes('expense-toolbar-actions'));
  assert.ok(cssSource.includes('.expense-toolbar-actions'));
  assert.ok(cssSource.includes('.expense-copy-json-button'));
});

test('Expense Sheet loads AI purchase recommendations and renders the top recommendation card', () => {
  assert.ok(jsxSource.includes("fetchBackendJson('/api/balance_sheet/purchase_recommendations'"));
  assert.ok(jsxSource.includes("fetchBackendJson('/api/balance_sheet/purchase_recommendations/regenerate'"));
  assert.ok(jsxSource.includes('purchaseRecommendations'));
  assert.ok(jsxSource.includes('expense-purchase-card'));
  assert.ok(jsxSource.includes("t('expense.purchase.title')"));
  assert.ok(jsxSource.includes("t('expense.purchase.regenerate')"));
  assert.ok(jsxSource.includes("t('expense.purchase.copy_json')"));
  assert.ok(jsxSource.includes("t('expense.purchase.copy_cover_prompt')"));
  assert.ok(cssSource.includes('.expense-purchase-card'));
  assert.ok(cssSource.includes('.expense-purchase-cover'));
  assert.ok(cssSource.includes('.expense-purchase-groups'));
});

test('Expense Sheet polls while purchase cover image is generating in the background', () => {
  assert.ok(jsxSource.includes("purchaseRecommendations?.cover_image?.status === 'generating'"));
  assert.ok(jsxSource.includes("t('expense.purchase.cover_generating')"));
  assert.ok(jsxSource.includes('purchaseCoverPollTimeoutRef'));
  assert.ok(jsxSource.includes('setTimeout(() => {'));
  assert.ok(jsxSource.includes('void fetchPurchaseRecommendations({ silent: true });'));
});

test('Expense Sheet purchase cover shows the full image without stretching to recommendation height', () => {
  assert.ok(cssSource.includes('align-items: start;'));
  assert.ok(cssSource.includes('aspect-ratio: 1 / 1;'));
  assert.ok(cssSource.includes('object-fit: contain;'));
  assert.equal(cssSource.includes('object-fit: cover;'), false);
});

test('Expense Sheet purchase recommendation copy actions use fallback clipboard support', () => {
  assert.ok(jsxSource.includes('JSON.stringify(purchaseRecommendations)'));
  assert.ok(jsxSource.includes('purchaseRecommendations?.cover_image?.prompt'));
  assert.ok(jsxSource.includes('handleCopyPurchaseJson'));
  assert.ok(jsxSource.includes('handleCopyCoverPrompt'));
  assert.ok(jsxSource.includes('writeTextWithFallback'));
});

test('Expense Sheet lets users dismiss purchase recommendation items', () => {
  assert.ok(jsxSource.includes("fetchBackendJson('/api/balance_sheet/purchase_recommendations/dismiss'"));
  assert.ok(jsxSource.includes('handleDismissPurchaseItem'));
  assert.ok(jsxSource.includes('expense-purchase-dismiss-button'));
  assert.ok(jsxSource.includes("t('expense.purchase.dismiss')"));
  assert.ok(jsxSource.includes('setPurchaseRecommendations((current) =>'));
  assert.ok(cssSource.includes('.expense-purchase-dismiss-button'));
});

test('Expense Sheet shows and clears dismissed purchase recommendation count', () => {
  assert.ok(jsxSource.includes("fetchBackendJson('/api/balance_sheet/purchase_recommendations/dismissed'"));
  assert.ok(jsxSource.includes("method: 'DELETE'"));
  assert.ok(jsxSource.includes('handleClearDismissedPurchaseItems'));
  assert.ok(jsxSource.includes("t('expense.purchase.dismissed_count'"));
  assert.ok(jsxSource.includes("t('expense.purchase.clear_dismissed')"));
});

test('Expense Sheet renders every budget item instead of a truncated preview', () => {
  assert.ok(jsxSource.includes('group.items.map((item) => ('));
  assert.equal(jsxSource.includes('group.items.slice(0, 4)'), false);
  assert.equal(jsxSource.includes('expense-budget-more'), false);
  assert.equal(jsxSource.includes("t('expense.more_items'"), false);
});

test('Expense Sheet lays out full budget groups without grid row gaps', () => {
  assert.match(cssSource, /\.expense-budget-groups\s*{[\s\S]*column-width:\s*260px;/);
  assert.match(cssSource, /\.expense-budget-groups\s*{[\s\S]*column-gap:\s*1\.2rem;/);
  assert.match(cssSource, /\.expense-budget-group\s*{[\s\S]*break-inside:\s*avoid;/);
  assert.equal(cssSource.includes('grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));'), false);
});

test('Expense Sheet balances dashboard cards across columns instead of pinning them to one side', () => {
  assert.match(cssSource, /\.expense-workspace\s*{[\s\S]*column-count:\s*2;/);
  assert.match(cssSource, /\.expense-workspace\s*{[\s\S]*column-gap:\s*1\.2rem;/);
  assert.match(cssSource, /\.expense-primary-column,\s*\n\.expense-secondary-column\s*{[\s\S]*display:\s*contents;/);
  assert.match(cssSource, /\.expense-workspace \.expense-section\s*{[\s\S]*break-inside:\s*avoid;/);
  assert.match(cssSource, /@media \(max-width:\s*1100px\)\s*{[\s\S]*\.expense-workspace\s*{[\s\S]*column-count:\s*1;/);
  assert.equal(cssSource.includes('grid-template-columns: minmax(0, 1.5fr) minmax(320px, 0.95fr);'), false);
});

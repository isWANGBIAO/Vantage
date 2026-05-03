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

test('Expense Sheet renders every budget item instead of a truncated preview', () => {
  assert.ok(jsxSource.includes('group.items.map((item) => ('));
  assert.equal(jsxSource.includes('group.items.slice(0, 4)'), false);
  assert.equal(jsxSource.includes('expense-budget-more'), false);
  assert.equal(jsxSource.includes("t('expense.more_items'"), false);
});

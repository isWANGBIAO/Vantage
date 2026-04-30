import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const plotsSource = readFileSync(new URL('./Plots.jsx', import.meta.url), 'utf8');

test('Plots promotes sleep schedule into the health lead charts', () => {
  assert.ok(plotsSource.includes("leadIds: ['sleep-schedule', 'weight-bodyfat', 'time-allocation']"));
});

test('Plots routes visible shell copy through the display language layer', () => {
  assert.ok(plotsSource.includes("useDisplayLanguage()"));
  assert.ok(plotsSource.includes("t('plots.hero.title')"));
  assert.ok(plotsSource.includes("t('plots.warning.title')"));
  assert.ok(plotsSource.includes("t('plots.summary.generated_at')"));
});

test('Plots refresh button clears the dashboard cache before reloading data', () => {
  assert.ok(plotsSource.includes("fetchBackendJson('/api/plots/refresh', {"));
  assert.ok(plotsSource.includes("method: 'POST'"));
  assert.ok(plotsSource.includes("retryPolicy: 'mutation'"));
  assert.ok(!plotsSource.includes("'/api/plots/data${refresh ? '?refresh=1' : ''}'"));
});

test('Plots maps backend affected_chart_ids warnings back to charts', () => {
  assert.ok(plotsSource.includes('warning?.affected_chart_ids'));
});

test('Plots keeps the balance chart out of empty finance sections', () => {
  assert.ok(plotsSource.includes("localizedCharts.filter((chart) => chart.id !== 'balance')"));
  assert.ok(!plotsSource.includes("key: 'finance'"));
  assert.ok(!plotsSource.includes("leadIds: ['balance']"));
});

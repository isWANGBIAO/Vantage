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

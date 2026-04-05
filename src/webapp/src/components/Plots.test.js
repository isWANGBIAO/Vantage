import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const plotsSource = readFileSync(new URL('./Plots.jsx', import.meta.url), 'utf8');

test('Plots page copy uses readable labels instead of mojibake', () => {
  assert.ok(plotsSource.includes('Visual Analysis'));
  assert.ok(plotsSource.includes('Data visualization'));
  assert.ok(plotsSource.includes('Loading plots...'));
  assert.ok(plotsSource.includes('No plots found'));
  assert.ok(plotsSource.includes('Click "Refresh Plots" to generate'));
  assert.ok(!plotsSource.includes('\u{1F4CA}'));
  assert.ok(!plotsSource.includes('\u23F3'));
});

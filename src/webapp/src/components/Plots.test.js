import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const plotsSource = readFileSync(new URL('./Plots.jsx', import.meta.url), 'utf8');

test('Plots promotes sleep schedule into the health lead charts', () => {
  assert.ok(plotsSource.includes("leadIds: ['sleep-schedule', 'weight-bodyfat', 'time-allocation']"));
});

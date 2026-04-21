import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('./App.jsx', import.meta.url), 'utf8');

test('App passes the current theme into chart-heavy screens', () => {
  assert.ok(appSource.includes('<ExpenseSheet theme={theme} />'));
  assert.ok(appSource.includes('<Plots theme={theme} />'));
});

test('App eagerly mounts prewarmed tabs on startup', () => {
  assert.ok(appSource.includes('<Dashboard />'));
  assert.ok(appSource.includes('<ProjectProgress />'));
  assert.ok(appSource.includes('<ExpenseSheet theme={theme} />'));
  assert.ok(appSource.includes('<Plots theme={theme} />'));
  assert.ok(appSource.includes('<SystemLogs />'));
  assert.ok(appSource.includes('<FaceHistory />'));
});

test('App keeps the global footer off full-height tabs including system logs', () => {
  assert.ok(appSource.includes("activeTab !== 'system logs'"));
});

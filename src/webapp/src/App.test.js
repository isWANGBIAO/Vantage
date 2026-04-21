import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('./App.jsx', import.meta.url), 'utf8');

test('App passes the current theme into chart-heavy screens', () => {
  assert.ok(appSource.includes('<ExpenseSheet theme={theme} />'));
  assert.ok(appSource.includes('<Plots theme={theme} />'));
});

test('App code-splits non-default tabs but still preloads them after startup', () => {
  assert.ok(appSource.includes('function lazyWithPreload'));
  assert.ok(appSource.includes('lazyWithPreload(() => import('));
  assert.ok(appSource.includes('backgroundTabsReady'));
  assert.ok(appSource.includes('Promise.all(BACKGROUND_TAB_COMPONENTS.map('));
  assert.ok(appSource.includes('.preload()'));
  assert.ok(appSource.includes('<Suspense fallback={null}>'));
  assert.equal(appSource.includes("import Dashboard from './components/Dashboard'"), false);
});

test('App keeps the global footer off full-height tabs including system logs', () => {
  assert.ok(appSource.includes("activeTab !== 'system logs'"));
});

test('App keeps dashboard prewarm mounted but passes visibility into Dashboard', () => {
  assert.ok(appSource.includes("<Dashboard isVisible={activeTab === 'dashboard'} />"));
});

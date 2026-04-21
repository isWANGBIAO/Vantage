import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('./App.jsx', import.meta.url), 'utf8');

test('App passes the current theme into chart-heavy screens', () => {
  assert.ok(appSource.includes('<ExpenseSheet theme={theme} />'));
  assert.ok(appSource.includes('<Plots theme={theme} />'));
});

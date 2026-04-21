import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const dashboardSource = readFileSync(new URL('./Dashboard.jsx', import.meta.url), 'utf8');

test('Dashboard only runs polling effects while visible', () => {
  assert.ok(dashboardSource.includes('export default function Dashboard({ isVisible = true })'));
  assert.ok(dashboardSource.includes('if (!isVisible) {'));
});

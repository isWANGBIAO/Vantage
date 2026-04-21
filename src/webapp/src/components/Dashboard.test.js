import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const dashboardSource = readFileSync(new URL('./Dashboard.jsx', import.meta.url), 'utf8');

test('Dashboard keeps startup prewarm polling active while delegating geolocation prompting to a policy helper', () => {
  assert.ok(dashboardSource.includes('export default function Dashboard({ isVisible = false })'));
  assert.ok(dashboardSource.includes('const statsInterval = setInterval(() => void fetchStats(), 5000);'));
  assert.ok(dashboardSource.includes('shouldUseDashboardGeolocation'));
  assert.ok(dashboardSource.includes('isVisible = false'));
});

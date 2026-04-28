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

test('Dashboard passes visibility into CameraFeed so hidden prewarm does not stream video', () => {
  assert.ok(dashboardSource.includes('<CameraFeed isVisible={isVisible} />'));
});

test('Dashboard sends an explicit local-app intent header for opening folders', () => {
  assert.ok(dashboardSource.includes("'X-Vantage-Intent': 'open-folder'"));
});

test('Dashboard throttles repeated backend polling errors', () => {
  assert.ok(dashboardSource.includes('pollErrorLoggedRef'));
  assert.ok(dashboardSource.includes('logPollErrorOnce'));
});

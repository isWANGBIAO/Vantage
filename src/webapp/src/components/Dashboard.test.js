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
  assert.ok(dashboardSource.includes('<CameraFeed isVisible={isVisible} privacyRevealed={mediaPrivacyRevealed} />'));
});

test('Dashboard sends an explicit local-app intent header for opening folders', () => {
  assert.ok(dashboardSource.includes("'X-Vantage-Intent': 'open-folder'"));
});

test('Dashboard throttles repeated backend polling errors', () => {
  assert.ok(dashboardSource.includes('pollErrorLoggedRef'));
  assert.ok(dashboardSource.includes('logPollErrorOnce'));
});

test('Dashboard marks truncated storage scans as a lower-bound estimate', () => {
  assert.ok(dashboardSource.includes('stats?.storage_scan_truncated'));
  assert.ok(dashboardSource.includes("t('dashboard.stat.storage_partial')"));
  assert.ok(dashboardSource.includes("'≥ '"));
});

test('Dashboard delegates focus-state rendering to a behavioral helper', () => {
  assert.ok(dashboardSource.includes('getFocusStatusPresentation,'));
  assert.ok(dashboardSource.includes('getFocusStatusPresentation(healthStats)'));
  assert.ok(dashboardSource.includes('title={t(focusStatusPresentation.titleKey)}'));
  assert.ok(dashboardSource.includes('value={t(focusStatusPresentation.valueKey, focusStatusPresentation.valueParams)}'));
  assert.ok(!dashboardSource.includes("title={t('dashboard.stat.focus_time')}"));
});

test('Dashboard downgrades stale focus UI on every health polling failure', () => {
  assert.ok(dashboardSource.includes('degradeFocusHealthSnapshot'));
  assert.ok(dashboardSource.includes('isValidFocusHealthSnapshot'));
  assert.ok(dashboardSource.includes('setHealthStats((previous) => degradeFocusHealthSnapshot(previous));'));
  assert.ok(dashboardSource.includes('if (!isValidFocusHealthSnapshot(data))'));
});

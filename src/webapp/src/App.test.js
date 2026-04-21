import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('./App.jsx', import.meta.url), 'utf8');

test('App passes the current theme into chart-heavy screens', () => {
  assert.ok(appSource.includes('theme={theme}'));
});

test('App lazy-loads non-default tabs and mounts them only after first visit', () => {
  assert.ok(appSource.includes("const Dashboard = lazy(() => import('./components/Dashboard'));"));
  assert.ok(appSource.includes("const Plots = lazy(() => import('./components/Plots'));"));
  assert.ok(appSource.includes("const [visitedTabs, setVisitedTabs] = useState(() => new Set([DEFAULT_TAB]));"));
  assert.ok(appSource.includes('if (!visitedTabs.has(tab.key)) {'));
});

test('App passes visibility into tab screens so hidden pages can stop polling', () => {
  assert.ok(appSource.includes('isVisible={isVisible}'));
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const actionPlanContainerSource = readFileSync(new URL('./ActionPlanContainer.jsx', import.meta.url), 'utf8');
const usagePanelSource = readFileSync(new URL('./UsagePanel.jsx', import.meta.url), 'utf8');
const displayCopySource = readFileSync(new URL('../utils/displayCopy.js', import.meta.url), 'utf8');

function loadUsagePanelSortHelper() {
  const start = usagePanelSource.indexOf('function toTimestamp');
  const end = usagePanelSource.indexOf('function SummaryCard');

  assert.notEqual(start, -1, 'expected toTimestamp helper in UsagePanel');
  assert.notEqual(end, -1, 'expected SummaryCard helper in UsagePanel');

  const helperSource = usagePanelSource.slice(start, end);
  const sandbox = { Date, globalThis: {} };

  vm.runInNewContext(`${helperSource}\nglobalThis.sortRowsByTimestamp = sortRowsByTimestamp;`, sandbox);

  return sandbox.globalThis.sortRowsByTimestamp;
}

test('ActionPlanContainer exposes a dedicated usage sub-tab', () => {
  assert.ok(actionPlanContainerSource.includes("setSubTab('usage')"));
  assert.ok(actionPlanContainerSource.includes("t('action_plan.tab.usage')"));
  assert.ok(actionPlanContainerSource.includes("<UsagePanel isVisible={isVisible && subTab === 'usage'} />"));
});

test('UsagePanel fetches backend usage aggregates and renders primary sections', () => {
  assert.ok(usagePanelSource.includes("fetchBackendJson('/api/usage'"));
  assert.ok(usagePanelSource.includes("t('usage.summary.total_tokens')"));
  assert.ok(usagePanelSource.includes("t('usage.summary.prompt_tokens')"));
  assert.ok(usagePanelSource.includes("t('usage.summary.completion_tokens')"));
  assert.ok(usagePanelSource.includes("t('usage.summary.completion_rate')"));
  assert.ok(usagePanelSource.includes("t('usage.summary.total_rate')"));
  assert.ok(usagePanelSource.includes("t('usage.summary.active_sources')"));
  assert.ok(usagePanelSource.includes("t('usage.latest_activity')"));
  assert.ok(usagePanelSource.includes("t('usage.by_source')"));
  assert.ok(usagePanelSource.includes("t('usage.speed_trend.title')"));
  assert.ok(usagePanelSource.includes("t('usage.speed_trend.subtitle')"));
  assert.ok(usagePanelSource.includes("t('usage.daily')"));
  assert.ok(usagePanelSource.includes("t('usage.recent_sessions')"));
  assert.ok(usagePanelSource.includes("t('usage.recent_calls')"));
  assert.equal(usagePanelSource.includes('Daily Usage'), false);
  assert.equal(usagePanelSource.includes('Recent Sessions'), false);
  assert.equal(usagePanelSource.includes('Recent Calls'), false);
});

test('UsagePanel aligns token counts with completion and total throughput labels', () => {
  assert.ok(usagePanelSource.includes('output_tokens_per_second'));
  assert.ok(usagePanelSource.includes('average_tokens_per_second'));
  assert.ok(usagePanelSource.includes("t('usage.label.prompt')"));
  assert.ok(usagePanelSource.includes("t('usage.label.completion')"));
  assert.ok(usagePanelSource.includes("t('usage.label.total')"));
  assert.ok(usagePanelSource.includes("t('usage.label.completion_rate')"));
  assert.ok(usagePanelSource.includes("t('usage.label.total_rate')"));
  assert.ok(usagePanelSource.includes("t('usage.label.share')"));
  assert.ok(usagePanelSource.includes("t('usage.label.prompt_share')"));
  assert.ok(usagePanelSource.includes("t('usage.label.completion_share')"));
  assert.equal(usagePanelSource.includes("label: 'Prompt'"), false);
  assert.equal(usagePanelSource.includes("label: 'Completion'"), false);
  assert.equal(usagePanelSource.includes("label: 'Total'"), false);
  assert.equal(usagePanelSource.includes("label: 'Completion tok/s'"), false);
  assert.equal(usagePanelSource.includes("label: 'Total tok/s'"), false);
  assert.equal(usagePanelSource.includes("label: 'Tokens'"), false);
  assert.equal(usagePanelSource.includes('Output Speed'), false);
});

test('UsagePanel renders speed trend from speed_series', () => {
  assert.ok(usagePanelSource.includes('speed_series'));
  assert.ok(usagePanelSource.includes('ReactECharts'));
  assert.ok(usagePanelSource.includes("t('usage.speed_trend.output_rate')"));
  assert.ok(usagePanelSource.includes("t('usage.speed_trend.total_rate')"));
  assert.ok(usagePanelSource.includes("t('usage.speed_trend.empty')"));
});

test('UsagePanel keeps explicit empty and error copy for missing history', () => {
  assert.ok(usagePanelSource.includes("t('usage.empty')"));
  assert.ok(usagePanelSource.includes("t('usage.error.load')"));
  assert.ok(usagePanelSource.includes("t('usage.refresh')"));
  assert.ok(usagePanelSource.includes("t('usage.daily.empty')"));
  assert.ok(usagePanelSource.includes("t('usage.recent_sessions.empty')"));
  assert.ok(usagePanelSource.includes("t('usage.recent_calls.empty')"));
  assert.equal(usagePanelSource.includes('No daily usage yet.'), false);
  assert.equal(usagePanelSource.includes('No recent sessions yet.'), false);
  assert.equal(usagePanelSource.includes('No recent calls yet.'), false);
});

test('UsagePanel display copy includes completed usage i18n keys', () => {
  [
    'usage.speed_trend.title',
    'usage.speed_trend.subtitle',
    'usage.speed_trend.empty',
    'usage.speed_trend.output_rate',
    'usage.speed_trend.total_rate',
    'usage.daily',
    'usage.daily.empty',
    'usage.recent_sessions',
    'usage.recent_sessions.empty',
    'usage.recent_calls',
    'usage.recent_calls.empty',
    'usage.label.duration',
    'usage.label.started',
    'usage.label.share',
  ].forEach((key) => {
    assert.ok(displayCopySource.includes(`'${key}'`), `expected display copy key ${key}`);
  });
});

test('UsagePanel does not poll while hidden', () => {
  assert.ok(usagePanelSource.includes('export default function UsagePanel({ isVisible = true } = {})'));
  assert.ok(usagePanelSource.includes('if (!isVisible) {'));
  assert.ok(usagePanelSource.includes('return undefined;'));
  assert.ok(usagePanelSource.includes('}, [isVisible, loadUsageDashboard]);'));
});

test('UsagePanel sorts timestamped rows newest first without mutating input', () => {
  const sortRowsByTimestamp = loadUsagePanelSortHelper();
  const rows = [
    { call_id: 'old', created_at: '2026-04-19T23:43:06+08:00' },
    { call_id: 'new', created_at: '2026-04-20T09:27:49+08:00' },
    { call_id: 'missing', created_at: null },
  ];

  const sorted = sortRowsByTimestamp(rows, 'created_at');

  assert.deepEqual(Array.from(sorted, (row) => row.call_id), ['new', 'old', 'missing']);
  assert.deepEqual(rows.map((row) => row.call_id), ['old', 'new', 'missing']);
});

test('UsagePanel uses call_id as the primary row key for recent calls tables', () => {
  assert.ok(
    usagePanelSource.includes("<tr key={row.id || row.call_id || row.session_id || row.date || `${index}`}>"),
    'expected DataTable row keys to prefer call_id before session_id',
  );
});

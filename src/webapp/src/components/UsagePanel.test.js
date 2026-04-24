import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const actionPlanContainerSource = readFileSync(new URL('./ActionPlanContainer.jsx', import.meta.url), 'utf8');
const usagePanelSource = readFileSync(new URL('./UsagePanel.jsx', import.meta.url), 'utf8');

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
  assert.ok(usagePanelSource.includes('Daily Usage'));
  assert.ok(usagePanelSource.includes('Recent Sessions'));
  assert.ok(usagePanelSource.includes('Recent Calls'));
});

test('UsagePanel aligns token counts with completion and total throughput labels', () => {
  assert.ok(usagePanelSource.includes('output_tokens_per_second'));
  assert.ok(usagePanelSource.includes('average_tokens_per_second'));
  assert.ok(usagePanelSource.includes("label: 'Prompt'"));
  assert.ok(usagePanelSource.includes("label: 'Completion'"));
  assert.ok(usagePanelSource.includes("label: 'Total'"));
  assert.ok(usagePanelSource.includes("label: 'Completion tok/s'"));
  assert.ok(usagePanelSource.includes("label: 'Total tok/s'"));
  assert.ok(usagePanelSource.includes('Share'));
  assert.ok(usagePanelSource.includes('Prompt Share'));
  assert.ok(usagePanelSource.includes('Completion Share'));
  assert.equal(usagePanelSource.includes("label: 'Tokens'"), false);
  assert.equal(usagePanelSource.includes('Output Speed'), false);
});

test('UsagePanel keeps explicit empty and error copy for missing history', () => {
  assert.ok(usagePanelSource.includes("t('usage.empty')"));
  assert.ok(usagePanelSource.includes("t('usage.error.load')"));
  assert.ok(usagePanelSource.includes("t('usage.refresh')"));
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

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const actionPlanContainerSource = readFileSync(new URL('./ActionPlanContainer.jsx', import.meta.url), 'utf8');
const usagePanelSource = readFileSync(new URL('./UsagePanel.jsx', import.meta.url), 'utf8');

test('ActionPlanContainer exposes a dedicated usage sub-tab', () => {
  assert.ok(actionPlanContainerSource.includes("setSubTab('usage')"));
  assert.ok(actionPlanContainerSource.includes('Usage'));
  assert.ok(actionPlanContainerSource.includes('<UsagePanel />'));
});

test('UsagePanel fetches backend usage aggregates and renders primary sections', () => {
  assert.ok(usagePanelSource.includes("fetchBackendJson('/api/usage'"));
  assert.ok(usagePanelSource.includes('Total Tokens'));
  assert.ok(usagePanelSource.includes('Completed Calls'));
  assert.ok(usagePanelSource.includes('Failed Calls'));
  assert.ok(usagePanelSource.includes('By Source'));
  assert.ok(usagePanelSource.includes('Daily Usage'));
  assert.ok(usagePanelSource.includes('Recent Sessions'));
  assert.ok(usagePanelSource.includes('Recent Calls'));
});

test('UsagePanel keeps explicit empty and error copy for missing history', () => {
  assert.ok(usagePanelSource.includes('No model usage recorded yet.'));
  assert.ok(usagePanelSource.includes('Failed to load usage dashboard.'));
  assert.ok(usagePanelSource.includes('Refresh'));
});

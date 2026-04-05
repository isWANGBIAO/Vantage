import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const actionPlanSource = readFileSync(new URL('./ActionPlan.jsx', import.meta.url), 'utf8');

test('ActionPlan refreshes chat context base after a new plan is generated', () => {
  assert.ok(actionPlanSource.includes("fetchBackendJson('/api/chat/context'"));
  assert.ok(actionPlanSource.includes('CHAT_CONTEXT_BASE_UPDATED_EVENT'));
});

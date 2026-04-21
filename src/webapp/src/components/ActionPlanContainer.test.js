import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const containerSource = readFileSync(new URL('./ActionPlanContainer.jsx', import.meta.url), 'utf8');

test('ActionPlanContainer folds chat into the plan workspace and keeps usage separate', () => {
  assert.ok(containerSource.includes('layoutMode="stacked"'));
  assert.ok(containerSource.includes('<ChatInterface embedded />'));
  assert.ok(containerSource.includes("setSubTab('usage')"));
  assert.equal(containerSource.includes("setSubTab('chat')"), false);
});

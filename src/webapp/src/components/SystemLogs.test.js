import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const systemLogsSource = readFileSync(new URL('./SystemLogs.jsx', import.meta.url), 'utf8');

test('SystemLogs polls only while visible and delegates severity coloring', () => {
  assert.ok(systemLogsSource.includes('export default function SystemLogs({ isVisible = false })'));
  assert.ok(systemLogsSource.includes('if (!isVisible)'));
  assert.ok(systemLogsSource.includes('fetchLogs();'));
  assert.ok(systemLogsSource.includes('const interval = setInterval(fetchLogs, 2000);'));
  assert.ok(systemLogsSource.includes('resolveSystemLogColor'));
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const systemLogsSource = readFileSync(new URL('./SystemLogs.jsx', import.meta.url), 'utf8');

test('SystemLogs starts polling on mount for startup prewarm and delegates severity coloring', () => {
  assert.ok(systemLogsSource.includes('export default function SystemLogs()'));
  assert.ok(systemLogsSource.includes('fetchLogs();'));
  assert.ok(systemLogsSource.includes('const interval = setInterval(fetchLogs, 2000);'));
  assert.ok(systemLogsSource.includes('resolveSystemLogColor'));
});

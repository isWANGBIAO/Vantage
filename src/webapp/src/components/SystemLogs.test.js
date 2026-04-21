import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const systemLogsSource = readFileSync(new URL('./SystemLogs.jsx', import.meta.url), 'utf8');

test('SystemLogs only polls while the tab is visible', () => {
  assert.ok(systemLogsSource.includes('export default function SystemLogs({ isVisible = true })'));
  assert.ok(systemLogsSource.includes('if (!isVisible) {'));
});

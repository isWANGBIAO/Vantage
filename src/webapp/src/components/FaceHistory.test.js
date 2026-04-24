import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const faceHistorySource = readFileSync(new URL('./FaceHistory.jsx', import.meta.url), 'utf8');

test('FaceHistory uses readable chart aria labels without mojibake', () => {
  assert.ok(faceHistorySource.includes('aria-label="实时黑眼圈分数图"'));
  assert.ok(faceHistorySource.includes('ariaLabel="实时黑眼圈分数图"'));
  assert.equal(faceHistorySource.includes('瀹炴椂榛戠溂鍦堝垎鏁板浘'), false);
});

test('FaceHistory throttles hidden live polling through visibility state', () => {
  assert.ok(faceHistorySource.includes('export default function FaceHistory({ isVisible = true } = {})'));
  assert.ok(faceHistorySource.includes('const visibleLivePollIntervalMs = 1000;'));
  assert.ok(faceHistorySource.includes('const hiddenLivePollIntervalMs = 30000;'));
  assert.ok(faceHistorySource.includes('const intervalMs = isVisible ? visibleLivePollIntervalMs : hiddenLivePollIntervalMs;'));
  assert.equal(faceHistorySource.includes('livePollIntervalMs = 100'), false);
});

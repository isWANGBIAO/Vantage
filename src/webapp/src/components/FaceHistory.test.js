import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const faceHistorySource = readFileSync(new URL('./FaceHistory.jsx', import.meta.url), 'utf8');

test('FaceHistory uses readable chart aria labels without mojibake', () => {
  assert.ok(faceHistorySource.includes("aria-label={t('face_history.live_chart_aria')}"));
  assert.ok(faceHistorySource.includes("ariaLabel={t('face_history.live_chart_aria')}"));
  assert.ok(faceHistorySource.includes("title={t(`face_history.trend.${key}`)}"));
  assert.equal(faceHistorySource.includes('aria-label="实时黑眼圈分数图"'), false);
  assert.equal(faceHistorySource.includes('ariaLabel="实时黑眼圈分数图"'), false);
  assert.equal(faceHistorySource.includes('瀹炴椂榛戠溂鍦堝垎鏁板浘'), false);
});

test('FaceHistory throttles hidden live polling through visibility state', () => {
  assert.ok(faceHistorySource.includes('export default function FaceHistory({ isVisible = true } = {})'));
  assert.ok(faceHistorySource.includes('const visibleLivePollIntervalMs = 1000;'));
  assert.ok(faceHistorySource.includes('const hiddenLivePollIntervalMs = 30000;'));
  assert.ok(faceHistorySource.includes('const intervalMs = isVisible ? visibleLivePollIntervalMs : hiddenLivePollIntervalMs;'));
  assert.ok(faceHistorySource.includes("`/api/v1/face/live?active=${isVisible ? '1' : '0'}`"));
  assert.equal(faceHistorySource.includes('livePollIntervalMs = 100'), false);
});

test('FaceHistory exposes external local models and privacy-gated sampling overlay', () => {
  assert.ok(faceHistorySource.includes('<FaceAnalysisSettings'));
  assert.ok(faceHistorySource.includes('onSaved={fetchReport}'));
  assert.ok(faceHistorySource.includes('localAnalysis'));
  assert.ok(faceHistorySource.includes('privacyRevealed && overlayUrl'));
  assert.ok(faceHistorySource.includes("t('face_local.disclaimer')"));
  assert.ok(faceHistorySource.includes("t('face_local.skipped')"));
});

test('FaceHistory can display zero-passing reports without missing extrema crashes', () => {
  assert.ok(faceHistorySource.includes('date={data.lightest?.date}'));
  assert.ok(faceHistorySource.includes('date={data.heaviest?.date}'));
});

test('FaceHistory presents separate left and right relative darkness scores', () => {
  assert.ok(faceHistorySource.includes('localAnalysis.latest_score_left'));
  assert.ok(faceHistorySource.includes('localAnalysis.latest_score_right'));
});

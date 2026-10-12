import test from 'node:test';
import assert from 'node:assert/strict';
import { assetPathForRecord, visibleTrend, safeRecordName, formatMetric } from './bodyAnalysisViewModel.js';

test('generated image references must belong to the report manifest and stay relative', () => {
  const manifest = ['masks/leg-0001.png'];
  assert.equal(assetPathForRecord('masks/leg-0001.png', manifest), '/api/v1/body-analysis/assets/masks/leg-0001.png');
  for (const path of ['../secret.png', '/absolute.png', 'masks/other.png', 'masks\\leg-0001.png', 'https://elsewhere/img.png']) {
    assert.equal(assetPathForRecord(path, manifest), null);
  }
});

test('scalp candidate and unreviewed records never enter a trend', () => {
  const report = { scalp: { records: [{ review_status: 'unreviewed', trend_eligible: false }], trend: [{ date: '2026-01-01', scalp_candidate_fraction_percent: 5 }] } };
  assert.deepEqual(visibleTrend(report, 'scalp'), []);
  const accepted = { leg: { records: [{ review_status: 'accepted', trend_eligible: true, timestamp_verified: true, captured_at: '2026-01-01T09:00:00' }], trend: [{ date: '2026-01-01', hair_count: 4, hair_density_per_mpx: 5 }] } };
  assert.deepEqual(visibleTrend(accepted, 'leg'), [{ date: '2026-01-01', hair_count: 4, hair_density_per_mpx: 5 }]);
});

test('missing metrics stay unknown and record names cannot show a source path', () => {
  assert.equal(formatMetric(null), '—');
  assert.equal(formatMetric(0), '0');
  assert.equal(safeRecordName('C:\\private\\photo.jpg'), 'photo.jpg');
});

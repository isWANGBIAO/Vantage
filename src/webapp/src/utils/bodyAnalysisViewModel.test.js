import test from 'node:test';
import assert from 'node:assert/strict';
import { assetPathForRecord, visibleTrend, visibleLegTrendSeries, safeRecordName, formatMetric } from './bodyAnalysisViewModel.js';

test('generated image references must belong to the report manifest and stay relative', () => {
  const manifest = ['masks/leg-0001.png'];
  assert.equal(assetPathForRecord('masks/leg-0001.png', manifest), '/api/v1/body-analysis/assets/masks/leg-0001.png');
  for (const path of ['../secret.png', '/absolute.png', 'masks/other.png', 'masks\\leg-0001.png', 'https://elsewhere/img.png']) {
    assert.equal(assetPathForRecord(path, manifest), null);
  }
});

test('new publication reloads same-named generated assets without widening the allowlist', () => {
  const manifest = ['masks/leg-0001.png'];
  const oldUrl = assetPathForRecord('masks/leg-0001.png', manifest, 'published-a');
  const newUrl = assetPathForRecord('masks/leg-0001.png', manifest, 'published-b');
  assert.equal(oldUrl, '/api/v1/body-analysis/assets/masks/leg-0001.png?v=published-a');
  assert.equal(newUrl, '/api/v1/body-analysis/assets/masks/leg-0001.png?v=published-b');
  assert.notEqual(oldUrl, newUrl);
  assert.equal(assetPathForRecord('masks/private.png', manifest, 'published-b'), null);
  assert.equal(assetPathForRecord('masks/leg-0001.png', manifest, '../bad'), '/api/v1/body-analysis/assets/masks/leg-0001.png');
});

test('automatic leg photo proxies may trend only when date and quality are verified', () => {
  const report = { leg: { records: [
    { review_status: 'unreviewed', trend_eligible: true, timestamp_verified: true, captured_at: '2026-01-01T09:00:00' },
    { review_status: 'unreviewed', trend_eligible: false, timestamp_verified: true, captured_at: '2026-01-02T09:00:00' },
  ], trend: [
    { date: '2026-01-01', hair_count: 4, hair_density_per_mpx: 5, n: 2 },
    { date: '2026-01-02', hair_count: 8, hair_density_per_mpx: 9 },
  ] } };
  assert.deepEqual(visibleTrend(report, 'leg'), [{ date: '2026-01-01', hair_count: 4, hair_density_per_mpx: 5, n: 2 }]);
  assert.deepEqual(visibleLegTrendSeries(report), [
    { key: 'hair_count', data: [['2026-01-01', 4, 2]] },
    { key: 'hair_density_per_mpx', data: [['2026-01-01', 5, 2]] },
  ]);
});

test('scalp candidate and unreviewed records never enter a trend', () => {
  const report = { scalp: { records: [{ review_status: 'unreviewed', trend_eligible: false }], trend: [{ date: '2026-01-01', scalp_candidate_fraction_percent: 5 }] } };
  assert.deepEqual(visibleTrend(report, 'scalp'), []);
  const accepted = { leg: { records: [{ review_status: 'accepted', trend_eligible: true, timestamp_verified: true, captured_at: '2026-01-01T09:00:00' }], trend: [{ date: '2026-01-01', hair_count: 4, hair_density_per_mpx: 5 }] } };
  assert.deepEqual(visibleTrend(accepted, 'leg'), [{ date: '2026-01-01', hair_count: 4, hair_density_per_mpx: 5 }]);
  const scalp = { scalp: { records: [{ review_status: 'unreviewed', trend_eligible: true, timestamp_verified: true, captured_at: '2026-01-01T09:00:00' }], trend: [{ date: '2026-01-01', hair_region_fraction_percent: 10, texture_fraction_percent: 3, scalp_candidate_fraction_percent: 2 }] } };
  assert.deepEqual(visibleTrend(scalp, 'scalp'), []);
});

test('missing metrics stay unknown and record names cannot show a source path', () => {
  assert.equal(formatMetric(null), '—');
  assert.equal(formatMetric(0), '0');
  assert.equal(safeRecordName('C:\\private\\photo.jpg'), 'photo.jpg');
});

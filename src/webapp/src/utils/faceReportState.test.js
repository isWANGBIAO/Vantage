import test from 'node:test';
import assert from 'node:assert/strict';

import { getFaceReportState } from './faceReportState.js';

test('getFaceReportState returns empty when backend has no cached report', () => {
  const state = getFaceReportState({ error: 'No report generated' });

  assert.deepEqual(state, {
    status: 'empty',
    data: null,
    error: null,
  });
});

test('getFaceReportState returns error for unexpected backend failures', () => {
  const state = getFaceReportState({ error: 'cache file unreadable' });

  assert.deepEqual(state, {
    status: 'error',
    data: null,
    error: 'cache file unreadable',
  });
});

test('getFaceReportState returns ready with report payload', () => {
  const payload = {
    trend_plot: '/plots/face_trend.png',
    lightest: { date: '2026-03-07', score: 12.3, url: '/photo/best.jpg' },
    heaviest: { date: '2026-03-01', score: 34.5, url: '/photo/worst.jpg' },
  };

  const state = getFaceReportState(payload);

  assert.equal(state.status, 'ready');
  assert.equal(state.error, null);
  assert.deepEqual(state.data, payload);
});

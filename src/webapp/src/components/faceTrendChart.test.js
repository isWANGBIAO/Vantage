import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildChartModel,
  buildPulseFrame,
  getTrendSummary,
} from './faceTrendChart.js';

test('buildChartModel returns svg path and mapped points for trend data', () => {
  const model = buildChartModel({
    points: [
      { timestamp: 1, datetime: '2026-03-13 08:00:00', score: 5 },
      { timestamp: 2, datetime: '2026-03-13 09:00:00', score: 7 },
    ],
    width: 320,
    height: 120,
  });

  assert.match(model.path, /^M /);
  assert.equal(model.points.length, 2);
  assert.ok(model.points[0].x < model.points[1].x);
  assert.ok(model.summary.latestLabel);
  assert.equal(model.showMarkers, false);
});

test('buildChartModel returns empty state when no points are provided', () => {
  const model = buildChartModel({
    points: [],
    width: 320,
    height: 120,
  });

  assert.equal(model.path, '');
  assert.equal(model.points.length, 0);
  assert.equal(model.summary.latestLabel, '--');
  assert.equal(model.showMarkers, false);
});

test('buildChartModel sorts realtime points by timestamp before drawing the line', () => {
  const model = buildChartModel({
    points: [
      { timestamp: 3, datetime: '2026-03-13 08:00:03', score: 8 },
      { timestamp: 1, datetime: '2026-03-13 08:00:01', score: 5 },
      { timestamp: 2, datetime: '2026-03-13 08:00:02', score: 6 },
    ],
    width: 320,
    height: 120,
  });

  assert.deepEqual(model.points.map((point) => point.timestamp), [1, 2, 3]);
});

test('buildPulseFrame builds a scrolling pulse path from latest score', () => {
  const pulse = buildPulseFrame({
    latestScore: 8,
    frame: 10,
    width: 500,
    height: 120,
  });

  assert.match(pulse.path, /^M /);
  assert.equal(pulse.points[0].x, 0);
  assert.ok(pulse.points.every((point) => point.y >= 0 && point.y <= 120));
});

test('getTrendSummary reports latest and average scores', () => {
  const summary = getTrendSummary([
    { timestamp: 1, datetime: '2026-03-13 08:00:00', score: 5 },
    { timestamp: 2, datetime: '2026-03-13 09:00:00', score: 7 },
  ]);

  assert.equal(summary.latestScore, '7.00');
  assert.equal(summary.averageScore, '6.00');
  assert.equal(summary.sampleCount, 2);
  assert.equal(summary.latestLabel, '2026-03-13 09:00');
});

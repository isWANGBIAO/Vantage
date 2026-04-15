import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildExpenseTrendChartModel,
  filterTrendPoints,
} from './expenseTrendChart.js';

const samplePoints = [
  { date: '2025-01-01', timestamp: Date.parse('2025-01-01'), balance: 1000, dailyAverage: 40 },
  { date: '2025-10-01', timestamp: Date.parse('2025-10-01'), balance: 1400, dailyAverage: 55 },
  { date: '2026-04-01', timestamp: Date.parse('2026-04-01'), balance: 1800, dailyAverage: 70 },
];

test('filterTrendPoints keeps recent windows relative to the latest point', () => {
  const lastYear = filterTrendPoints(samplePoints, '1y');

  assert.equal(lastYear.length, 2);
  assert.deepEqual(
    lastYear.map((point) => point.date),
    ['2025-10-01', '2026-04-01'],
  );

  const allPoints = filterTrendPoints(samplePoints, 'all');
  assert.equal(allPoints.length, 3);
});

test('buildExpenseTrendChartModel returns drawable paths and axis ticks', () => {
  const model = buildExpenseTrendChartModel({
    points: samplePoints,
    width: 900,
    height: 320,
  });

  assert.ok(model.balancePath.startsWith('M '));
  assert.ok(model.spendPath.startsWith('M '));
  assert.equal(model.xTicks.length, 3);
  assert.equal(model.balanceTicks.length, 4);
  assert.equal(model.spendTicks.length, 4);
  assert.equal(model.latestPoint.balance, 1800);
  assert.equal(model.latestPoint.dailyAverage, 70);
});

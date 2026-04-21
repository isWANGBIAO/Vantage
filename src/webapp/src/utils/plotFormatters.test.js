import test from 'node:test';
import assert from 'node:assert/strict';

import { buildChartOption } from './plotFormatters.js';

const chart = {
  id: 'sleep-schedule',
  option: {
    xAxis: { type: 'category', data: ['2026-04-20'] },
    yAxis: { type: 'value' },
    series: [{ type: 'line', name: 'Sleep', data: [23.5] }],
  },
};

test('buildChartOption returns dark chart chrome for the dark theme', () => {
  const option = buildChartOption(chart, 'dark');

  assert.equal(option.textStyle.color, '#f3f7f5');
  assert.equal(option.tooltip.backgroundColor, 'rgba(6, 12, 10, 0.94)');
  assert.equal(option.xAxis.axisLabel.color, 'rgba(214, 232, 224, 0.72)');
  assert.equal(option.yAxis.axisPointer.label.backgroundColor, '#244739');
});

test('buildChartOption keeps the light palette for the light theme', () => {
  const option = buildChartOption(chart, 'light');

  assert.equal(option.textStyle.color, '#10231c');
  assert.equal(option.tooltip.backgroundColor, 'rgba(9, 22, 17, 0.92)');
  assert.equal(option.xAxis.axisLabel.color, 'rgba(19, 45, 37, 0.62)');
  assert.equal(option.yAxis.axisPointer.label.backgroundColor, '#183a2f');
});

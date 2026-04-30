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

test('balance tooltip shows monthly income for forecast points', () => {
  const option = buildChartOption({
    id: 'balance',
    option: {
      xAxis: { type: 'time' },
      yAxis: { type: 'value' },
      series: [
        {
          type: 'line',
          name: '预测期末现金+股票',
          data: [{ value: ['2026-08-31', 119159], monthlyIncome: 30834 }],
        },
      ],
    },
  }, 'light', 'zh-CN');

  const html = option.tooltip.formatter([
    {
      axisValueLabel: '2026-08-31',
      marker: '●',
      seriesName: '预测期末现金+股票',
      value: ['2026-08-31', 119159],
      data: { value: ['2026-08-31', 119159], monthlyIncome: 30834 },
    },
  ]);

  assert.match(html, /2026-08-31/);
  assert.match(html, /预测期末现金\+股票/);
  assert.match(html, /当月收入/);
  assert.match(html, /¥30834/);
});

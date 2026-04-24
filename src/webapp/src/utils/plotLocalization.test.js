import test from 'node:test';
import assert from 'node:assert/strict';

import { buildChartOption, formatSummaryValue } from './plotFormatters.js';
import { localizePlotChart, localizePlotWarnings } from './plotLocalization.js';

test('localizePlotChart translates backend chart metadata and option labels for English', () => {
  const chart = {
    id: 'time-allocation',
    title: '每日时间分配',
    description: '把睡眠、手机屏幕和剩余时间放进同一张可缩放堆叠图里，替代原始静态柱状图。',
    summary: [
      { label: '平均睡眠', value: '8.2 h' },
      { label: '样本天数', value: '3 天' },
    ],
    option: {
      legend: {
        selected: {
          睡眠时间: true,
        },
      },
      yAxis: { name: '小时' },
      series: [
        { name: '睡眠时间', type: 'bar', data: [['2026-04-20', 8.2]] },
        { name: '手机屏幕使用时间', type: 'bar', data: [['2026-04-20', 5.1]] },
      ],
    },
  };

  const localized = localizePlotChart(chart, 'en-US');

  assert.equal(localized.title, 'Daily Time Allocation');
  assert.equal(
    localized.description,
    'Sleep, phone screen time, and remaining hours are stacked into one zoomable chart instead of a static bar plot.',
  );
  assert.deepEqual(localized.summary.map((item) => item.label), ['Average Sleep', 'Sample Days']);
  assert.equal(localized.summary[1].value, '3 days');
  assert.deepEqual(localized.option.legend.selected, { 'Sleep Duration': true });
  assert.equal(localized.option.yAxis.name, 'Hours');
  assert.deepEqual(localized.option.series.map((series) => series.name), ['Sleep Duration', 'Phone Screen Time']);
});

test('buildChartOption localizes tooltip labels and duration units for English plots', () => {
  const option = buildChartOption(
    {
      id: 'time-allocation',
      option: {
        xAxis: { type: 'category' },
        yAxis: { name: '小时' },
        series: [{ name: '睡眠时间', type: 'bar', data: [['2026-04-20', 8.5]] }],
      },
    },
    'dark',
    'en-US',
  );

  const tooltip = option.tooltip.formatter([
    {
      marker: '•',
      axisValueLabel: '2026-04-20',
      seriesName: 'Sleep Duration',
      value: ['2026-04-20', 8.5],
    },
  ]);

  assert.equal(option.yAxis.name, 'Hours');
  assert.equal(option.series[0].name, 'Sleep Duration');
  assert.match(tooltip, /Sleep Duration: 8 h 30 min/);
  assert.equal(formatSummaryValue({ value: 2, unit: '天' }, 'en-US'), '2 days');
});

test('localizePlotWarnings translates generated warning copy while preserving source snippets', () => {
  const warnings = [
    {
      id: 'time-invalid-rows',
      title: '已跳过 2 条异常时间数据',
      message: '这些记录未参与时间类图表计算。请修改 Excel 源数据后刷新 Plots 页面。',
      details: [
        '2026-04-20：睡眠时间 未知，手机屏幕使用时间 12小时，原因：时间数据无效',
        '其余 3 条异常记录已省略，请直接检查 Excel 源数据。',
      ],
      affected_chart_ids: ['time-allocation'],
    },
  ];

  const localized = localizePlotWarnings(warnings, 'en-US');

  assert.equal(localized[0].title, 'Skipped 2 anomalous time rows');
  assert.equal(
    localized[0].message,
    'These rows were excluded from time charts. Fix the Excel source data, then refresh the Plots page.',
  );
  assert.equal(
    localized[0].details[0],
    '2026-04-20: sleep time unknown, phone screen time 12 hours, reason: invalid time data',
  );
  assert.equal(localized[0].details[1], '3 more anomalous rows are hidden. Inspect the Excel source data directly.');
});

test('localizePlotWarnings translates running extraction issue details for English mode', () => {
  const warnings = [
    {
      id: 'running-missing-main',
      title: '跑步主图存在未完整提取的记录',
      message: '这些记录会让配速 / 心率 / 距离出现断点。请按原文修正 Excel 后再 refresh charts。',
      details: [
        '未知日期：缺少 配速、心率异常值 255；原文：跑步 3km',
        '2026-04-20：距离 < 1 km（0.50 km）；原文：test',
      ],
      affected_chart_ids: ['running'],
    },
  ];

  const localized = localizePlotWarnings(warnings, 'en-US');

  assert.equal(localized[0].title, 'Running main chart has incompletely extracted records');
  assert.equal(
    localized[0].details[0],
    'unknown date: Missing pace, Abnormal heart rate 255; source: 跑步 3km',
  );
  assert.equal(localized[0].details[1], '2026-04-20: Distance < 1 km (0.50 km); source: test');
});

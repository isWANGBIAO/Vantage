import test from 'node:test';
import assert from 'node:assert/strict';

import { buildChartOption, formatSummaryValue } from './plotFormatters.js';
import { localizePlotChart, localizePlotWarnings } from './plotLocalization.js';

test('sleep recent-record summaries are distinct from all-history reference means', () => {
  const chart = localizePlotChart({ id: 'sleep-schedule', summary: [
    { label: '近45条平均入睡', value: '01:30' }, { label: '近45条平均起床', value: '09:00' },
  ] }, 'en-US');
  assert.deepEqual(chart.summary.map((item) => item.label), ['Bedtime Mean (Last 45 Records)', 'Wake-Time Mean (Last 45 Records)']);
});

test('balance chart localizes actual and daily consumption metadata', () => {
  const chart = localizePlotChart({
    id: 'balance',
    title: '资产与消费',
    description: '把总资产、分账户资产和实际消费、日均消费放进同一张可筛选图，而不是只看一张静态资金曲线。',
    summary: [{ label: '最新实际消费', value: 100 }, { label: '最新日均消费', value: 10 }],
    option: {
      yAxis: [{ name: '资产 / 消费 (元)' }, { name: '日均消费 (元/天)' }],
      series: [{ name: '实际消费' }, { name: '日均消费' }],
    },
  }, 'en-US');
  assert.equal(chart.title, 'Assets and Consumption');
  assert.equal(chart.description, 'Combine total assets, account-level assets, actual consumption, and daily consumption into one filterable chart instead of one static balance curve.');
  assert.deepEqual(chart.summary.map((item) => item.label), ['Latest Actual Consumption', 'Latest Daily Consumption']);
  assert.equal(chart.option.yAxis[0].name, 'Assets / Consumption (RMB)');
  assert.equal(chart.option.yAxis[1].name, 'Daily Consumption (RMB/day)');
  assert.deepEqual(chart.option.series.map((item) => item.name), ['Actual Consumption', 'Daily Consumption']);
});

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

test('localizePlotChart translates radar goal comparison windows for English', () => {
  const chart = {
    id: 'radar-goal',
    title: '\u76ee\u6807\u8fbe\u6210\u7387\u96f7\u8fbe\u56fe',
    description:
      '\u540c\u65f6\u5bf9\u6bd4\u5168\u90e8\u5386\u53f2\u3001\u8fd130\u5929\u548c\u6700\u65b0\u4e00\u5929\u7684\u76ee\u6807\u8fbe\u6210\u7387\uff0c\u907f\u514d\u628a\u957f\u671f\u5e73\u5747\u8bef\u770b\u6210\u5f53\u5929\u8868\u73b0\u3002',
    summary: [
      { label: '\u5386\u53f2\u7efc\u5408\u8fbe\u6210\u7387', value: '65 %' },
      { label: '\u8fd130\u5929\u7efc\u5408\u8fbe\u6210\u7387', value: '72 %' },
      { label: '\u6700\u65b0\u4e00\u5929\u7efc\u5408\u8fbe\u6210\u7387', value: '85 %' },
    ],
    option: {
      legend: {
        data: ['\u5168\u90e8\u5386\u53f2\u5e73\u5747', '\u8fd130\u5929\u5e73\u5747', '\u6700\u65b0\u4e00\u5929'],
      },
      series: [
        {
          name: '\u76ee\u6807\u8fbe\u6210\u7387',
          data: [
            { name: '\u5168\u90e8\u5386\u53f2\u5e73\u5747', value: [65, 72] },
            { name: '\u8fd130\u5929\u5e73\u5747', value: [72, 80] },
            { name: '\u6700\u65b0\u4e00\u5929', value: [85, 90] },
          ],
        },
      ],
    },
  };

  const localized = localizePlotChart(chart, 'en-US');

  assert.equal(
    localized.description,
    'Compare all-history, last-30-day, and latest-day goal achievement so long-term averages are not mistaken for daily performance.',
  );
  assert.deepEqual(localized.summary.map((item) => item.label), [
    'Historical Overall Achievement',
    'Last 30 Days Overall Achievement',
    'Latest Day Overall Achievement',
  ]);
  assert.deepEqual(localized.option.legend.data, ['All-History Average', 'Last 30 Days Average', 'Latest Day']);
  assert.deepEqual(localized.option.series[0].data.map((item) => item.name), [
    'All-History Average',
    'Last 30 Days Average',
    'Latest Day',
  ]);
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
      message: '部分跑步记录缺少距离或用时，或包含明确异常值。请核对 Time.xlsx「记录」页的运动原文后刷新图表。',
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
    localized[0].message,
    'Some running records lack distance or duration, or contain an explicit anomalous value. Check the exercise text on the Records sheet in Time.xlsx, then refresh charts.',
  );
  assert.equal(
    localized[0].details[0],
    'unknown date: Missing pace, Abnormal heart rate 255; source: 跑步 3km',
  );
  assert.equal(localized[0].details[1], '2026-04-20: Distance < 1 km (0.50 km); source: test');
});

test('missing heart rate HRC empty state localizes without an error', () => {
  const chart = localizePlotChart({
    id: 'running-hrc',
    title: 'Heart Rate Cost of Running (HRC)',
    empty: true,
    error: null,
    message: '暂无心率数据，HRC 暂不计算。其他跑步指标照常显示。',
  }, 'en-US');

  assert.equal(chart.empty, true);
  assert.equal(chart.error, null);
  assert.equal(chart.message, 'No heart rate data is recorded, so HRC is unavailable. Other running metrics remain visible.');
});

test('running warnings direct English users to Time exercise text', () => {
  const messages = [
    '部分记录的用时、步频或步幅数值需要核对。请核对 Time.xlsx「记录」页的运动原文后刷新图表。',
    '部分记录的距离、用时或已记录心率需要核对，未计入 HRC 趋势。请核对 Time.xlsx「记录」页的运动原文。',
    '这些异常记录未计入相应跑步趋势。请核对 Time.xlsx「记录」页的运动原文。',
  ];
  const warnings = messages.map((message) => ({
    message,
    details: ['其余 2 条异常记录已省略，请核对 Time.xlsx「记录」页的运动原文。'],
  }));

  const localized = localizePlotWarnings(warnings, 'en-US');

  for (const warning of localized) {
    assert.match(warning.message, /exercise text on the Records sheet in Time\.xlsx/);
    assert.doesNotMatch(warning.message, /export/i);
    assert.equal(warning.details[0], '2 more anomalous records are hidden. Check the exercise text on the Records sheet in Time.xlsx.');
  }
});

test('running form summary identifies calculated stride values in both languages', () => {
  const chart = {
    id: 'running-form',
    summary: [{ label: '计算/估算步幅', value: '2次' }],
  };

  assert.deepEqual(localizePlotChart(chart, 'zh-CN').summary, [{ label: '计算/估算步幅', value: '2次' }]);
  const plural = localizePlotChart(chart, 'en-US').summary[0];
  assert.equal(plural.label, 'Calculated/Estimated Stride');
  assert.equal(plural.value, '2 times');
  const singular = localizePlotChart({ ...chart, summary: [{ label: '计算/估算步幅', value: '1次' }] }, 'en-US').summary[0];
  assert.equal(singular.label, 'Calculated/Estimated Stride');
  assert.equal(singular.value, '1 time');
});

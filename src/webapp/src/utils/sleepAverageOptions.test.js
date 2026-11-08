import test from 'node:test';
import assert from 'node:assert/strict';
import process from 'node:process';
import * as echarts from 'echarts';
import { buildChartOption } from './plotFormatters.js';
import { buildSleepAverageOption, buildSleepAverageStatistics, normalizeSleepAverageMode } from './sleepAverageOptions.js';

const DAY = 86_400_000;
const date = (timestamp) => new Date(timestamp).toISOString().slice(0, 10);
function fixture(rows) {
  return buildChartOption({ id: 'sleep-schedule', option: {
    color: ['#ad7aa4', '#579e50'],
    xAxis: { type: 'time' }, yAxis: { type: 'value', min: 12, max: 48 },
    legend: { data: ['入睡时间', '起床时间'] },
    dataZoom: [{ type: 'inside', start: 55, end: 95 }, { type: 'slider', start: 55, end: 95 }],
    series: [0, 1].map((index) => ({ name: index ? '起床时间' : '入睡时间', type: 'line',
      data: rows.map((row) => [row[0], row[index + 1]]) })),
  } }, 'light');
}
const days = (start, length, bed = 25, wake = 33) => Array.from({ length }, (_item, index) =>
  [date(Date.parse(`${start}T00:00:00Z`) + index * DAY), typeof bed === 'function' ? bed(index) : bed, wake]);
const get = (option, prefix, index = 0) => option.series.find((series) => series.id === `sleep-${prefix}-${index}`);

test('unsupported mode defaults to the approved monthly horizontal segments', () => {
  for (const value of [undefined, null, '', 'week', 3, {}, ['total']]) assert.equal(normalizeSleepAverageMode(value), 'segments');
  for (const value of ['total', 'segments', 'monthly', 'rolling']) assert.equal(normalizeSleepAverageMode(value), value);
});

test('clock averages use unwrapped hours across midnight rather than averaging modulo clocks', () => {
  const option = fixture([['2026-01-01', 23.5, 31], ['2026-01-02', 24.5, 33]]);
  const stats = buildSleepAverageStatistics(option);
  assert.equal(stats.series[0].total, 24);
  assert.equal(stats.series[1].total, 32);
  assert.match(buildSleepAverageOption(option, 'total').tooltip.formatter([{ axisValue: '2026-01-01' }]), /历史平均: 00:00/);
});

test('totals are weighted by distinct daily observations, not an average of monthly means', () => {
  const rows = [...days('2026-01-01', 7, 24), ...days('2026-02-01', 21, 28)];
  assert.equal(buildSleepAverageStatistics(fixture(rows)).series[0].total, 27);
});

test('duplicate dates use last valid record; invalid later duplicates cannot erase it or satisfy thresholds', () => {
  const rows = days('2026-01-01', 6, 24);
  rows.push(['2026-01-06', 28, 35], ['2026-01-06', null, null], ['2026-01-06', '29', false]);
  const stats = buildSleepAverageStatistics(fixture(rows));
  assert.equal(stats.series[0].count, 6);
  assert.equal(stats.series[0].daily.at(-1)[1], 28);
  assert.equal(stats.series[0].months[0].value, null);
  assert.ok(stats.series[0].rolling.every((row) => row[1] === null));
});

test('invalid dates, coercible scalars, booleans, infinity and non-unwrapped values are excluded', () => {
  const rows = [['2026-02-30', 25, 33], ['2026-01-01', '25', 33],
    ['2026-01-02', null, null], ['2026-01-03', false, Infinity], ['2026-01-04', 0, 90], ['2026-01-05', 25, 33]];
  const stats = buildSleepAverageStatistics(fixture(rows));
  assert.equal(stats.series[0].count, 1);
  assert.equal(stats.series[1].count, 2);
  assert.equal(stats.series[0].total, 25);
  assert.ok(!stats.series[0].daily.some((row) => row[0] === '2026-02-30'));
});

test('daily and rolling gaps remain explicit nulls and never become observed zero', () => {
  const rows = days('2026-01-01', 45).filter((row) => row[0] !== '2026-01-20');
  const option = buildSleepAverageOption(fixture(rows), 'rolling');
  const missingDay = Date.parse('2026-01-20T00:00:00Z');
  assert.deepEqual(get(option, 'daily').data.find((row) => row[0] === missingDay), [missingDay, null]);
  assert.deepEqual(get(option, 'rolling').data.find((row) => row[0] === missingDay), [missingDay, null]);
  assert.equal(get(option, 'daily').connectNulls, false);
  assert.equal(get(option, 'rolling').connectNulls, false);
});

test('monthly statistics require seven distinct days and retain empty calendar months', () => {
  const rows = [...days('2026-01-01', 7, 24), ...days('2026-03-01', 6, 28)];
  const months = buildSleepAverageStatistics(fixture(rows)).series[0].months;
  assert.deepEqual(months.map((month) => [month.key, month.count, month.value]), [
    ['2026-01', 7, 24], ['2026-02', 0, null], ['2026-03', 6, null],
  ]);
});

test('trailing mean requires fifteen distinct records and uses thirty calendar days, not thirty rows', () => {
  const stats = buildSleepAverageStatistics(fixture(days('2026-01-01', 45, (index) => 24 + index / 100))).series[0];
  assert.equal(stats.rolling[13][1], null);
  assert.equal(stats.rolling[14][1], 24.07);
  assert.ok(Math.abs(stats.rolling[30][1] - 24.155) < 1e-10);
  const sparse = days('2026-01-01', 90).filter((_row, index) => index % 3 === 0);
  assert.ok(buildSleepAverageStatistics(fixture(sparse)).series[0].rolling.every((row) => row[1] === null));
});

test('duplicate records never warm a trailing mean prematurely', () => {
  const rows = days('2026-01-01', 14);
  rows.push(...Array.from({ length: 20 }, () => rows.at(-1)));
  const stats = buildSleepAverageStatistics(fixture(rows));
  assert.ok(stats.series[0].rolling.every((row) => row[1] === null));
  assert.equal(stats.series[0].rollingCounts.get('2026-01-14'), 14);
});

test('history before a zoom boundary contributes to the same trailing mean', () => {
  const option = fixture(days('2026-01-01', 90, (index) => index < 45 ? 24 : 28));
  const left = buildSleepAverageOption(option, 'rolling');
  const zoomed = buildSleepAverageOption({ ...option, dataZoom: [{ type: 'inside', start: 80, end: 100 }] }, 'rolling');
  assert.deepEqual(get(left, 'rolling').data, get(zoomed, 'rolling').data);
  assert.equal(get(left, 'daily').markLine.data[0].yAxis, get(zoomed, 'daily').markLine.data[0].yAxis);
});

test('all four modes preserve original axes, palette, zoom selection and input objects', () => {
  const base = fixture(days('2026-01-01', 80));
  const before = JSON.stringify(base);
  for (const mode of ['total', 'segments', 'monthly', 'rolling']) {
    const result = buildSleepAverageOption(base, mode);
    assert.equal(result.xAxis, base.xAxis);
    assert.equal(result.yAxis, base.yAxis);
    assert.equal(result.color, base.color);
    assert.deepEqual(result.dataZoom.map((zoom) => [zoom.start, zoom.end, zoom.filterMode]), [[55, 95, 'none'], [55, 95, 'none']]);
    assert.equal(get(result, 'daily').lineStyle.color, base.color[0]);
    assert.deepEqual(result.legend, base.legend);
  }
  assert.equal(JSON.stringify(base), before);
});

test('only the selected overlay contains marks while daily records and references always remain', () => {
  const base = fixture(days('2026-01-01', 80));
  for (const mode of ['total', 'segments', 'monthly', 'rolling']) {
    const result = buildSleepAverageOption(base, mode);
    assert.equal(get(result, 'daily').data.length, 80);
    assert.equal(get(result, 'daily').markLine.data.length, 1);
    for (const overlay of ['segments', 'rolling']) assert.equal(get(result, overlay).data.length > 0, mode === overlay);
    assert.equal(get(result, 'monthly').data.length > 0, mode === 'monthly');
  }
});

test('horizontal month segments are disconnected custom marks and never extend past the last source day', () => {
  const stats = buildSleepAverageStatistics(fixture(days('2026-01-05', 70)));
  const result = buildSleepAverageOption(fixture(days('2026-01-05', 70)), 'segments');
  const segments = get(result, 'segments');
  assert.equal(segments.type, 'custom');
  assert.equal(segments.clip, true);
  assert.equal(segments.data[0][0], stats.start);
  assert.equal(segments.data.at(-1)[1], stats.end);
  assert.equal(segments.data.at(-1)[3], 1);
  assert.ok(segments.data.every((row) => row[0] <= row[1] && row[1] <= stats.end));
  const shape = segments.renderItem({}, { value: (index) => [1, 29, 25, 1][index], coord: ([x, y]) => [x * 10, y * 10] });
  assert.equal(shape.type, 'line');
  assert.equal(shape.shape.y1, shape.shape.y2);
  assert.deepEqual(shape.style.lineDash, [4, 4]);
});

test('monthly lines leave missing months empty and mark partial-month connections as dashed', () => {
  const rows = [...days('2026-01-01', 31), ...days('2026-03-01', 10)];
  const result = buildSleepAverageOption(fixture(rows), 'monthly');
  assert.deepEqual(get(result, 'monthly').data.map((row) => row[1]), [25, null, null]);
  assert.deepEqual(get(result, 'monthly-partial').data.map((row) => row[1]), [null, null, 25]);
  assert.equal(get(result, 'monthly-partial').lineStyle.type, 'dashed');
  assert.equal(get(result, 'monthly').connectNulls, false);
});

test('English grouped tooltip reports day, mode values, independent counts and fixed history', () => {
  const result = buildSleepAverageOption(fixture(days('2026-01-01', 45)), 'rolling', 'en-US');
  const html = result.tooltip.formatter([{ axisValue: Date.parse('2026-02-05T12:00:00Z') }]);
  assert.match(html, /2026-02-05/);
  assert.match(html, /Bedtime: 01:00/);
  assert.match(html, /Wake time: 09:00/);
  assert.match(html, /Trailing 30-day mean: 01:00 \(30 days\)/);
  assert.match(html, /All-history mean: 01:00 \(45 days\)/);
  assert.ok(!html.includes('undefined'));
});

test('partial-month tooltip names the actual source cutoff, not a future month end', () => {
  const result = buildSleepAverageOption(fixture(days('2026-01-01', 45)), 'segments');
  const html = result.tooltip.formatter([{ axisValue: '2026-02-10' }]);
  assert.match(html, /截至2026-02-14/);
  assert.ok(!html.includes('2026-02-28'));
});

test('invalid tooltip parameters cannot inject HTML or fabricate a date', () => {
  const result = buildSleepAverageOption(fixture(days('2026-01-01', 45)), 'segments');
  assert.equal(result.tooltip.formatter([{ axisValue: '<img src=x onerror=alert(1)>' }]), '');
  assert.equal(result.tooltip.formatter([]), '');
});

test('one-day history still shows real daily points and a valid reference but no invented statistics', () => {
  const option = buildSleepAverageOption(fixture([['2026-01-01', 25, 33]]), 'segments');
  assert.deepEqual(get(option, 'daily').data, [[Date.parse('2026-01-01T00:00:00Z'), 25]]);
  assert.equal(get(option, 'daily').markLine.data[0].yAxis, 25);
  assert.equal(get(option, 'daily').showSymbol, true);
  assert.equal(get(option, 'daily').symbolSize(null, { dataIndex: 0 }), 4);
  assert.deepEqual(get(option, 'segments').data, []);
});

test('two independent partial-month edges cannot draw a dashed connector between complete months', () => {
  const rows = days('2026-01-05', 100);
  const option = buildSleepAverageOption(fixture(rows), 'monthly');
  assert.equal(get(option, 'monthly').data.length, 4);
  assert.deepEqual(get(option, 'monthly-partial-start').data.map((row) => row[1]), [25, 25, null, null]);
  assert.deepEqual(get(option, 'monthly-partial').data.map((row) => row[1]), [null, null, 25, 25]);
});

test('only isolated daily records get visible points, without adding a point to every daily observation', () => {
  const rows = [['2026-01-01', 25, 33], ['2026-01-03', 26, 34], ['2026-01-04', 27, 35]];
  const option = buildSleepAverageOption(fixture(rows), 'total');
  assert.equal(get(option, 'daily').symbolSize(null, { dataIndex: 0 }), 4);
  assert.equal(get(option, 'daily').symbolSize(null, { dataIndex: 2 }), 0);
  assert.equal(get(option, 'daily').symbolSize(null, { dataIndex: 3 }), 0);
});

test('the first partial historical month uses its own cutoff rather than the latest month date', () => {
  const option = buildSleepAverageOption(fixture(days('2026-01-05', 100)), 'segments');
  const html = option.tooltip.formatter([{ axisValue: '2026-01-12' }]);
  assert.match(html, /截至2026-01-31/);
  assert.ok(!html.includes('截至2026-04-14'));
});

test('missing data, unsupported payloads and unreasonable date spans safely keep the legacy chart', () => {
  for (const option of [{}, { series: [] }, fixture([]), fixture([['2026-01-01', null, null]]), fixture([['1800-01-01', 25, 33], ['2026-01-01', 25, 33]])]) {
    assert.equal(buildSleepAverageOption(option), option);
  }
});

test('leap days use UTC calendar windows with no local timezone shift', () => {
  const stats = buildSleepAverageStatistics(fixture(days('2024-02-01', 40)));
  assert.equal(stats.series[0].months[0].count, 29);
  assert.equal(stats.series[0].months[0].end, Date.parse('2024-02-29T00:00:00Z'));
  assert.equal(stats.series[0].rollingCounts.get('2024-03-01'), 30);
});

test('actual ECharts SVG rendering accepts all four modes, references, stable axes and zoom windows', () => {
  const base = fixture(days('2026-01-01', 100, (index) => 25 + index / 100));
  const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 900, height: 440 });
  try {
    for (const mode of ['total', 'segments', 'monthly', 'rolling']) {
      const option = { ...buildSleepAverageOption(base, mode), animation: false };
      chart.setOption(option, { notMerge: true });
      const svg = chart.renderToSVGString();
      assert.ok(svg.startsWith('<svg'));
      assert.ok(!/NaN|undefined/.test(svg));
      assert.match(svg, /历史 入睡/);
      assert.match(svg, /历史 起床/);
      assert.deepEqual(chart.getModel().getComponent('yAxis').axis.scale.getExtent(), [12, 48]);
      assert.deepEqual(chart.getOption().dataZoom.map((zoom) => [zoom.start, zoom.end]), [[55, 95], [55, 95]]);
      assert.equal(chart.getOption().series.find((series) => series.id === 'sleep-daily-0').markLine.data[0].yAxis,
        buildSleepAverageStatistics(base).series[0].total);
    }
  } finally { chart.dispose(); }
});

test('actual ECharts custom month marks are separate horizontal shapes with a dashed partial endpoint', () => {
  const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 900, height: 440 });
  try {
    const base = fixture(days('2026-01-01', 100));
    const option = buildSleepAverageOption({ ...base, dataZoom: [] }, 'segments');
    chart.setOption({ ...option, animation: false });
    const model = chart.getModel().getSeries().find((series) => series.id === 'sleep-segments-0');
    const shapes = [];
    chart.getViewOfSeriesModel(model).group.traverse((element) => {
      if (element.type === 'line') shapes.push(element);
    });
    assert.equal(shapes.length, 4);
    assert.ok(shapes.every((element) => element.shape.y1 === element.shape.y2 && element.shape.x1 < element.shape.x2));
    assert.deepEqual(shapes.at(-1).style.lineDash, [4, 4]);
    assert.ok(shapes.slice(0, -1).every((element) => element.style.lineDash === undefined));
    assert.ok(shapes.at(-1).shape.x2 <= chart.getWidth());
  } finally { chart.dispose(); }
});

test('actual ECharts daily SVG leaves an explicit gap instead of bridging missing days', () => {
  const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 900, height: 440 });
  try {
    const rows = days('2026-01-01', 40).filter((row) => row[0] !== '2026-01-20');
    const base = fixture(rows);
    chart.setOption({ ...buildSleepAverageOption({ ...base, dataZoom: [] }, 'total'), animation: false });
    const paths = chart.renderToSVGString().match(/<path[^>]+>/g) || [];
    const line = paths.find((path) => path.includes('stroke="#ad7aa4"') && path.includes('stroke-width="2"'));
    assert.ok(line, 'bedtime daily series must render');
    const commands = line.match(/d="([^"]+)"/)[1];
    assert.equal((commands.match(/M/g) || []).length, 2);
  } finally { chart.dispose(); }
});

test('actual ECharts daily, rolling, monthly and custom layers share UTC coordinates in Shanghai and DST timezones', () => {
  const originalTimezone = process.env.TZ;
  try {
    for (const timezone of ['Asia/Shanghai', 'America/New_York', 'Europe/Berlin', 'UTC']) {
      process.env.TZ = timezone;
      const base = fixture(days('2026-03-01', 75));
      const stats = buildSleepAverageStatistics(base);
      for (const mode of ['total', 'segments', 'monthly', 'rolling']) {
        const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 900, height: 440 });
        try {
          const option = buildSleepAverageOption({ ...base, dataZoom: [] }, mode);
          assert.equal(option.useUTC, true);
          chart.setOption({ ...option, animation: false });
          const series = chart.getModel().getSeries();
          const valueAt = (id, index = 0) => {
            const data = series.find((item) => item.id === id).getData();
            return data.get(data.mapDimension('x'), index);
          };
          const first = valueAt('sleep-daily-0');
          assert.equal(first, Date.parse('2026-03-01T00:00:00Z'), `${timezone}/${mode} daily`);
          const dstDay = valueAt('sleep-daily-0', 28);
          assert.equal(dstDay, Date.parse('2026-03-29T00:00:00Z'), `${timezone}/${mode} DST date`);
          assert.match(option.tooltip.formatter([{ axisValue: first }]), /^2026-03-01<br>/);
          assert.match(option.tooltip.formatter([{ axisValue: dstDay }]), /^2026-03-29<br>/);
          if (mode === 'segments') assert.equal(valueAt('sleep-segments-0'), first);
          if (mode === 'rolling') assert.equal(valueAt('sleep-rolling-0', 28), dstDay);
          if (mode === 'monthly') assert.equal(valueAt('sleep-monthly-0'), stats.series[0].months[0].midpoint);
          assert.ok(!/NaN|undefined/.test(chart.renderToSVGString()));
        } finally { chart.dispose(); }
      }
    }
  } finally {
    if (originalTimezone === undefined) delete process.env.TZ;
    else process.env.TZ = originalTimezone;
  }
});

test('explicit bare-date bounds use the same UTC domain as numeric sleep layers', () => {
  const base = fixture(days('2026-01-01', 45));
  const axis = { ...base.xAxis, min: '2026-01-01', max: '2026-03-01', axisLabel: { color: 'green' } };
  const result = buildSleepAverageOption({ ...base, xAxis: axis }, 'segments');
  assert.equal(result.xAxis.min, Date.parse('2026-01-01T00:00:00Z'));
  assert.equal(result.xAxis.max, Date.parse('2026-03-01T00:00:00Z'));
  assert.deepEqual(result.xAxis.axisLabel, axis.axisLabel);
  assert.equal(axis.min, '2026-01-01');
  assert.equal(axis.max, '2026-03-01');
});

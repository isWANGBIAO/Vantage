const DAY_MS = 86_400_000;
const MAX_DAYS = 36_600;
export const SLEEP_AVERAGE_MODES = Object.freeze(['total', 'segments', 'monthly', 'rolling']);

export function normalizeSleepAverageMode(value) {
  return SLEEP_AVERAGE_MODES.includes(value) ? value : 'segments';
}

function dateTimestamp(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const timestamp = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === value ? timestamp : null;
}

const dateString = (timestamp) => new Date(timestamp).toISOString().slice(0, 10);
const isHour = (value) => typeof value === 'number' && Number.isFinite(value) && value >= 12 && value < 72;
const clock = (value) => {
  if (!Number.isFinite(value)) return null;
  const minutes = ((Math.round(value * 60) % 1440) + 1440) % 1440;
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
};
const englishLanguage = (language) => String(language).toLowerCase().startsWith('en');
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[char]);

function observationMap(series) {
  const result = new Map();
  for (const item of Array.isArray(series?.data) ? series.data : []) {
    const row = Array.isArray(item) ? item : item?.value;
    if (!Array.isArray(row)) continue;
    const timestamp = dateTimestamp(row[0]);
    if (timestamp !== null && isHour(row[1])) result.set(timestamp, row[1]);
  }
  return result;
}

/** Statistics use complete source records, never the visible dataZoom window. */
export function buildSleepAverageStatistics(baseOption) {
  const originals = baseOption?.series;
  if (!Array.isArray(originals) || originals.length < 2) return null;
  const maps = originals.slice(0, 2).map(observationMap);
  const dates = [...new Set(maps.flatMap((map) => [...map.keys()]))].sort((a, b) => a - b);
  if (!dates.length) return null;
  const start = dates[0], end = dates.at(-1);
  if ((end - start) / DAY_MS > MAX_DAYS) return null;
  const dailyDates = [];
  for (let timestamp = start; timestamp <= end; timestamp += DAY_MS) dailyDates.push(timestamp);
  const firstDate = new Date(start);
  firstDate.setUTCDate(1);
  const monthStarts = [];
  let monthStart = +firstDate;
  while (monthStart <= end) {
    const current = new Date(monthStart);
    current.setUTCMonth(current.getUTCMonth() + 1);
    const next = +current;
    monthStarts.push({ start: monthStart, next });
    monthStart = next;
  }
  const series = maps.map((map) => {
    const daily = dailyDates.map((timestamp) => [dateString(timestamp), map.get(timestamp) ?? null]);
    const values = [...map.values()];
    const total = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
    let rollingSum = 0, rollingCount = 0;
    const rollingCounts = new Map();
    const rolling = daily.map((row, index) => {
      if (isHour(row[1])) { rollingSum += row[1]; rollingCount += 1; }
      if (index >= 30 && isHour(daily[index - 30][1])) {
        rollingSum -= daily[index - 30][1]; rollingCount -= 1;
      }
      rollingCounts.set(row[0], rollingCount);
      // A missing day remains a gap even if previous observations suffice.
      return [row[0], isHour(row[1]) && rollingCount >= 15 ? rollingSum / rollingCount : null];
    });
    const buckets = new Map();
    for (const [timestamp, value] of map) {
      const key = dateString(timestamp).slice(0, 7);
      const bucket = buckets.get(key) || { sum: 0, count: 0 };
      bucket.sum += value; bucket.count += 1; buckets.set(key, bucket);
    }
    const months = monthStarts.map(({ start: first, next }) => {
      const key = dateString(first).slice(0, 7), bucket = buckets.get(key);
      const observedStart = Math.max(first, start), observedEnd = Math.min(next - DAY_MS, end);
      return {
        key, start: observedStart, end: observedEnd,
        midpoint: observedStart + Math.floor((observedEnd - observedStart) / DAY_MS / 2) * DAY_MS,
        partial: first < start || next - DAY_MS > end,
        count: bucket?.count ?? 0,
        value: bucket && bucket.count >= 7 ? bucket.sum / bucket.count : null,
      };
    });
    return { daily, total, count: values.length, rolling, rollingCounts, months };
  });
  return { start, end, firstDate: dateString(start), latestDate: dateString(end), series };
}

function pointDate(params) {
  const item = Array.isArray(params) ? params.find((entry) => entry?.axisValue != null) || params[0] : params;
  let value = item?.axisValue ?? item?.value?.[0] ?? item?.data?.value?.[0] ?? item?.data?.[0];
  if (typeof value === 'string' && dateTimestamp(value) !== null) return value;
  if (typeof value === 'string') value = Date.parse(value);
  return typeof value === 'number' && Number.isFinite(value) ? dateString(Math.floor(value / DAY_MS) * DAY_MS) : null;
}

function partialMonthlyData(months, edge) {
  const active = edge === 'start' ? months[0]?.partial : months.at(-1)?.partial;
  if (!active) return [];
  return months.map((month, index) => [month.midpoint,
    (edge === 'start' ? index < 2 : index >= months.length - 2) ? month.value : null]);
}

function segmentRenderer(color) {
  return (_params, api) => {
    const start = api.coord([api.value(0), api.value(2)]);
    const end = api.coord([api.value(1), api.value(2)]);
    const gap = Math.min(3, Math.max(0, (end[0] - start[0]) / 5));
    return {
      type: 'line',
      shape: { x1: start[0] + gap, y1: start[1], x2: end[0] - gap, y2: end[1] },
      style: { stroke: color, lineWidth: 3, lineCap: 'round', ...(api.value(3) ? { lineDash: [4, 4] } : {}) },
    };
  };
}

function utcAxisBounds(axis) {
  if (Array.isArray(axis)) {
    const result = axis.map(utcAxisBounds);
    return result.every((item, index) => item === axis[index]) ? axis : result;
  }
  if (!axis || typeof axis !== 'object') return axis;
  const min = dateTimestamp(axis.min), max = dateTimestamp(axis.max);
  if (min === null && max === null) return axis;
  return { ...axis, ...(min !== null ? { min } : {}), ...(max !== null ? { max } : {}) };
}

/** Add average overlays to the existing sleep chart without changing its layout. */
export function buildSleepAverageOption(baseOption, selectedMode = 'segments', language = 'zh-CN') {
  const statistics = buildSleepAverageStatistics(baseOption);
  if (!statistics) return baseOption;
  const mode = normalizeSleepAverageMode(selectedMode), english = englishLanguage(language);
  const originalSeries = baseOption.series.slice(0, 2);
  const names = english ? ['Bedtime', 'Wake time'] : ['入睡', '起床'];
  const unknown = english ? 'No record' : '无记录';
  const formatClock = (value) => clock(value) || unknown;
  const dailyMaps = statistics.series.map((series) => new Map(series.daily));
  const rollingMaps = statistics.series.map((series) => new Map(series.rolling));
  const tooltipFormatter = (params) => {
    const date = pointDate(params);
    if (!date) return '';
    const rows = [escapeHtml(date)];
    statistics.series.forEach((series, index) => {
      rows.push(`${escapeHtml(names[index])}: ${formatClock(dailyMaps[index].get(date))}`);
      if (mode === 'segments' || mode === 'monthly') {
        const month = series.months.find((item) => item.key === date.slice(0, 7));
        const label = english ? 'Monthly mean' : '月平均';
        const count = english ? `${month?.count ?? 0} days` : `${month?.count ?? 0}天`;
        const partial = month?.partial ? english ? `, through ${dateString(month.end)}` : `，截至${dateString(month.end)}` : '';
        rows.push(`${label}: ${formatClock(month?.value)} (${count}${partial})`);
      } else if (mode === 'rolling') {
        const count = series.rollingCounts.get(date) ?? 0;
        rows.push(`${english ? 'Trailing 30-day mean' : '过去30天平均'}: ${formatClock(rollingMaps[index].get(date))} (${count}${english ? ' days' : '天'})`);
      }
      rows.push(`${english ? 'All-history mean' : '历史平均'}: ${formatClock(series.total)} (${series.count}${english ? ' days' : '天'})`);
    });
    return rows.join('<br>');
  };
  const resultSeries = [];
  statistics.series.forEach((series, index) => {
    const source = originalSeries[index], name = names[index];
    const color = source.lineStyle?.color || source.itemStyle?.color || baseOption.color?.[index] || 'currentColor';
    const labelColor = baseOption.textStyle?.color || source.label?.color || color;
    const legendName = source.name || name;
    const isolated = new Set(series.daily.flatMap((row, dailyIndex) => isHour(row[1])
      && !isHour(series.daily[dailyIndex - 1]?.[1]) && !isHour(series.daily[dailyIndex + 1]?.[1]) ? [dailyIndex] : []));
    resultSeries.push({
      ...source, id: `sleep-daily-${index}`, name: legendName,
      data: series.daily.map(([date, value]) => [dateTimestamp(date), value]), connectNulls: false, showSymbol: true, symbol: 'circle',
      symbolSize: (_value, params) => isolated.has(params.dataIndex) ? 4 : 0,
      itemStyle: { ...source.itemStyle, color },
      lineStyle: { ...source.lineStyle, color, width: mode === 'total' ? 2 : 1.1, opacity: mode === 'total' ? 0.75 : 0.28, shadowBlur: 0 },
      markLine: {
        silent: true, symbol: 'none', animation: false,
        lineStyle: { color, type: 'dashed', width: 1, opacity: 0.6 },
        label: { show: true, position: 'insideEndTop', color: labelColor, fontSize: 11,
          formatter: `${english ? 'Historical' : '历史'} ${name} ${formatClock(series.total)}` },
        data: series.total === null ? [] : [{ yAxis: series.total }],
      },
    });
    const common = { type: 'line', showSymbol: false, connectNulls: false, smooth: false,
      animationDurationUpdate: 220, itemStyle: { color }, lineStyle: { color, width: 3 }, z: 4 };
    // Use the daily legend identity for all overlays so the native legend stays two items.
    resultSeries.push({ ...common, id: `sleep-rolling-${index}`, name: legendName,
      data: mode === 'rolling' ? series.rolling.map(([date, value]) => [dateTimestamp(date), value]) : [] });
    resultSeries.push({ ...common, id: `sleep-monthly-${index}`, name: legendName,
      showSymbol: true, symbol: 'circle', symbolSize: 6,
      data: mode === 'monthly' ? series.months.map((month) => [month.midpoint, month.partial ? null : month.value]) : [] });
    resultSeries.push({ ...common, id: `sleep-monthly-partial-${index}`, name: legendName,
      showSymbol: true, symbol: 'emptyCircle', symbolSize: 6,
      lineStyle: { color, width: 3, type: 'dashed' },
      data: mode === 'monthly' ? partialMonthlyData(series.months, 'end') : [] });
    resultSeries.push({ ...common, id: `sleep-monthly-partial-start-${index}`, name: legendName,
      showSymbol: true, symbol: 'emptyCircle', symbolSize: 6,
      lineStyle: { color, width: 3, type: 'dashed' },
      data: mode === 'monthly' ? partialMonthlyData(series.months, 'start') : [] });
    resultSeries.push({
      id: `sleep-segments-${index}`, name: legendName, type: 'custom',
      data: mode === 'segments' ? series.months.filter((month) => month.value !== null)
        .map((month) => [month.start, month.end, month.value, month.partial ? 1 : 0]) : [],
      encode: { x: [0, 1], y: 2 }, renderItem: segmentRenderer(color), clip: true, z: 4,
    });
  });
  return {
    ...baseOption,
    // ECharts interprets bare ISO dates as local midnight. Keep every rendered
    // layer on numeric UTC-midnight coordinates, matching the UTC calendar stats.
    useUTC: true,
    xAxis: utcAxisBounds(baseOption.xAxis),
    tooltip: { ...baseOption.tooltip, trigger: 'axis', confine: true, formatter: tooltipFormatter },
    // Filtering only hides marks: it must never recompute historical/monthly/rolling means.
    dataZoom: Array.isArray(baseOption.dataZoom) ? baseOption.dataZoom.map((zoom) => ({ ...zoom, filterMode: 'none' })) : baseOption.dataZoom,
    series: [...resultSeries, ...baseOption.series.slice(2)],
  };
}

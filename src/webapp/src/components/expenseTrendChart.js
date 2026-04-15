const DEFAULT_PADDING = { top: 24, right: 72, bottom: 44, left: 72 };
const DAY_MS = 24 * 60 * 60 * 1000;
const RANGE_DAYS = {
  '6m': 183,
  '1y': 365,
  all: null,
};

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function round(value, digits = 2) {
  return Number(value.toFixed(digits));
}

function formatDateTick(timestamp, spanDays) {
  const date = new Date(timestamp);
  const pad = (value) => String(value).padStart(2, '0');

  if (spanDays > 370) {
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}`;
  }

  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function formatAxisTick(value) {
  if (!Number.isFinite(value)) return '--';

  const absolute = Math.abs(value);
  if (absolute >= 10000) {
    return `${round(value / 10000, 1)}w`;
  }

  return round(value, 0).toLocaleString('zh-CN');
}

function normalizePoints(points) {
  return (Array.isArray(points) ? points : [])
    .filter((point) => Number.isFinite(Number(point?.timestamp)))
    .map((point) => ({
      ...point,
      timestamp: Number(point.timestamp),
      balance: Number.isFinite(Number(point.balance)) ? Number(point.balance) : null,
      dailyAverage: Number.isFinite(Number(point.dailyAverage)) ? Number(point.dailyAverage) : null,
    }))
    .sort((left, right) => left.timestamp - right.timestamp);
}

function buildPath(points) {
  if (!points.length) return '';
  return points
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${round(point.x)} ${round(point.y)}`)
    .join(' ');
}

function buildAreaPath(points, baseline) {
  if (!points.length) return '';

  const start = points[0];
  const end = points[points.length - 1];
  return [
    `M ${round(start.x)} ${round(baseline)}`,
    ...points.map((point) => `L ${round(point.x)} ${round(point.y)}`),
    `L ${round(end.x)} ${round(baseline)}`,
    'Z',
  ].join(' ');
}

function buildLinearTicks(min, max, count = 4) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    return [];
  }

  if (min === max) {
    return Array.from({ length: count }, (_, index) => min + index);
  }

  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, index) => min + (step * index));
}

function mapSeriesPoints(points, {
  key,
  chartLeft,
  chartRight,
  chartTop,
  chartBottom,
  minTimestamp,
  maxTimestamp,
  minValue,
  maxValue,
}) {
  const timestampSpan = Math.max(1, maxTimestamp - minTimestamp);
  const valueSpan = Math.max(1, maxValue - minValue);

  return points
    .filter((point) => point[key] !== null)
    .map((point) => ({
      ...point,
      value: point[key],
      x: chartLeft + (((point.timestamp - minTimestamp) / timestampSpan) * (chartRight - chartLeft)),
      y: chartBottom - (((point[key] - minValue) / valueSpan) * (chartBottom - chartTop)),
    }));
}

export function filterTrendPoints(points, range) {
  const normalized = normalizePoints(points);
  const days = RANGE_DAYS[range] ?? null;

  if (!normalized.length || days === null) {
    return normalized;
  }

  const minTimestamp = normalized[normalized.length - 1].timestamp - (days * DAY_MS);
  const filtered = normalized.filter((point) => point.timestamp >= minTimestamp);
  return filtered.length ? filtered : normalized.slice(-1);
}

export function buildExpenseTrendChartModel({
  points,
  width,
  height,
  padding = DEFAULT_PADDING,
}) {
  const normalized = normalizePoints(points);
  const chartLeft = padding.left;
  const chartRight = width - padding.right;
  const chartTop = padding.top;
  const chartBottom = height - padding.bottom;

  if (!normalized.length) {
    return {
      balancePath: '',
      balanceAreaPath: '',
      spendPath: '',
      xTicks: [],
      balanceTicks: [],
      spendTicks: [],
      latestPoint: null,
      balancePoints: [],
      spendPoints: [],
    };
  }

  const minTimestamp = normalized[0].timestamp;
  const maxTimestamp = normalized[normalized.length - 1].timestamp;
  const spanDays = Math.max(1, (maxTimestamp - minTimestamp) / DAY_MS);

  const balanceValues = normalized
    .map((point) => point.balance)
    .filter((value) => value !== null);
  const spendValues = normalized
    .map((point) => point.dailyAverage)
    .filter((value) => value !== null);

  const balanceMin = balanceValues.length ? Math.min(...balanceValues) : 0;
  const balanceMax = balanceValues.length ? Math.max(...balanceValues) : 1;
  const spendMin = spendValues.length ? Math.min(...spendValues) : 0;
  const spendMax = spendValues.length ? Math.max(...spendValues) : 1;

  const balancePadding = Math.max(1, (balanceMax - balanceMin) * 0.12);
  const spendPadding = Math.max(1, (spendMax - spendMin) * 0.16);

  const resolvedBalanceMin = balanceValues.length ? Math.max(0, balanceMin - balancePadding) : 0;
  const resolvedBalanceMax = balanceValues.length ? balanceMax + balancePadding : 1;
  const resolvedSpendMin = spendValues.length ? Math.max(0, spendMin - spendPadding) : 0;
  const resolvedSpendMax = spendValues.length ? spendMax + spendPadding : 1;

  const balancePoints = mapSeriesPoints(normalized, {
    key: 'balance',
    chartLeft,
    chartRight,
    chartTop,
    chartBottom,
    minTimestamp,
    maxTimestamp,
    minValue: resolvedBalanceMin,
    maxValue: resolvedBalanceMax,
  });
  const spendPoints = mapSeriesPoints(normalized, {
    key: 'dailyAverage',
    chartLeft,
    chartRight,
    chartTop,
    chartBottom,
    minTimestamp,
    maxTimestamp,
    minValue: resolvedSpendMin,
    maxValue: resolvedSpendMax,
  });

  const balanceTicks = buildLinearTicks(resolvedBalanceMin, resolvedBalanceMax).map((value) => {
    const y = chartBottom - (((value - resolvedBalanceMin) / Math.max(1, resolvedBalanceMax - resolvedBalanceMin)) * (chartBottom - chartTop));
    return {
      value,
      label: formatAxisTick(value),
      y: clamp(y, chartTop, chartBottom),
    };
  });

  const spendTicks = buildLinearTicks(resolvedSpendMin, resolvedSpendMax).map((value) => {
    const y = chartBottom - (((value - resolvedSpendMin) / Math.max(1, resolvedSpendMax - resolvedSpendMin)) * (chartBottom - chartTop));
    return {
      value,
      label: formatAxisTick(value),
      y: clamp(y, chartTop, chartBottom),
    };
  });

  const tickTimestamps = [minTimestamp, minTimestamp + ((maxTimestamp - minTimestamp) / 2), maxTimestamp];
  const xTicks = tickTimestamps.map((timestamp, index) => ({
    timestamp,
    x: index === 0 ? chartLeft : index === 2 ? chartRight : (chartLeft + chartRight) / 2,
    label: formatDateTick(timestamp, spanDays),
  }));

  return {
    balancePath: buildPath(balancePoints),
    balanceAreaPath: buildAreaPath(balancePoints, chartBottom),
    spendPath: buildPath(spendPoints),
    xTicks,
    balanceTicks,
    spendTicks,
    latestPoint: normalized[normalized.length - 1],
    balancePoints,
    spendPoints,
    chartLeft,
    chartRight,
    chartTop,
    chartBottom,
  };
}

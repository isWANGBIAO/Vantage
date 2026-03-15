const DEFAULT_PADDING = 18;

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function round(value, digits = 2) {
  return Number(value.toFixed(digits));
}

function normalizePoints(points) {
  return (Array.isArray(points) ? points : [])
    .filter((point) => Number.isFinite(Number(point?.score)))
    .map((point) => ({
      timestamp: Number(point.timestamp),
      datetime: point.datetime || '',
      score: Number(point.score),
    }))
    .sort((left, right) => left.timestamp - right.timestamp);
}

function formatDateTimeLabel(datetime) {
  if (!datetime) {
    return '--';
  }

  return String(datetime).slice(0, 16);
}

function formatTickLabel(timestamp, spanMs) {
  if (!Number.isFinite(Number(timestamp))) {
    return '--';
  }

  const date = new Date(Number(timestamp) * 1000);
  const pad = (value) => String(value).padStart(2, '0');
  if (spanMs <= 24 * 60 * 60 * 1000) {
    return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }
  if (spanMs <= 30 * 24 * 60 * 60 * 1000) {
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function buildPath(points) {
  if (!points.length) {
    return '';
  }

  return points
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${round(point.x, 2)} ${round(point.y, 2)}`)
    .join(' ');
}

function buildTicks(points, width, padding, minTimestamp, maxTimestamp) {
  if (!points.length) {
    return [];
  }

  if (Number.isFinite(Number(minTimestamp)) && Number.isFinite(Number(maxTimestamp))) {
    const resolvedMinTimestamp = Number(minTimestamp);
    const resolvedMaxTimestamp = Number(maxTimestamp);
    const spanMs = Math.max(0, (resolvedMaxTimestamp - resolvedMinTimestamp) * 1000);
    const middleTimestamp = resolvedMinTimestamp + ((resolvedMaxTimestamp - resolvedMinTimestamp) / 2);
    return [
      { x: padding, label: formatTickLabel(resolvedMinTimestamp, spanMs) },
      { x: width / 2, label: formatTickLabel(middleTimestamp, spanMs) },
      { x: width - padding, label: formatTickLabel(resolvedMaxTimestamp, spanMs) },
    ];
  }

  if (points.length === 1) {
    return [
      {
        x: points[0].x,
        label: formatTickLabel(points[0].timestamp, 0),
      },
    ];
  }

  const first = points[0];
  const last = points[points.length - 1];
  const middle = points[Math.floor(points.length / 2)];
  const spanMs = Math.max(0, (last.timestamp - first.timestamp) * 1000);
  const ticks = [first, middle, last]
    .map((point) => ({
      x: clamp(point.x, padding, width - padding),
      label: formatTickLabel(point.timestamp, spanMs),
    }))
    .filter((tick, index, arr) => arr.findIndex((candidate) => candidate.label === tick.label) === index);

  return ticks;
}

export function getTrendSummary(points) {
  const normalized = normalizePoints(points);
  if (!normalized.length) {
    return {
      latestScore: '--',
      averageScore: '--',
      sampleCount: 0,
      latestLabel: '--',
    };
  }

  const latest = normalized[normalized.length - 1];
  const total = normalized.reduce((sum, point) => sum + point.score, 0);

  return {
    latestScore: latest.score.toFixed(2),
    averageScore: (total / normalized.length).toFixed(2),
    sampleCount: normalized.length,
    latestLabel: formatDateTimeLabel(latest.datetime),
  };
}

export function buildChartModel({
  points,
  width,
  height,
  padding = DEFAULT_PADDING,
  minTimestamp,
  maxTimestamp,
}) {
  const normalized = normalizePoints(points);
  const summary = getTrendSummary(normalized);
  if (!normalized.length) {
    return {
      path: '',
      points: [],
      ticks: [],
      summary,
      showMarkers: false,
    };
  }

  const resolvedMinTimestamp = Number.isFinite(Number(minTimestamp))
    ? Number(minTimestamp)
    : normalized[0].timestamp;
  const resolvedMaxTimestamp = Number.isFinite(Number(maxTimestamp))
    ? Number(maxTimestamp)
    : normalized[normalized.length - 1].timestamp;
  const scoreValues = normalized.map((point) => point.score);
  const minScore = Math.min(...scoreValues);
  const maxScore = Math.max(...scoreValues);
  const scoreSpan = Math.max(1, maxScore - minScore);
  const lowerBound = minScore - (scoreSpan === 1 ? 1 : scoreSpan * 0.15);
  const upperBound = maxScore + (scoreSpan === 1 ? 1 : scoreSpan * 0.15);
  const timestampSpan = Math.max(1, resolvedMaxTimestamp - resolvedMinTimestamp);

  const mappedPoints = normalized.map((point, index) => {
    const hasFixedTimeDomain = resolvedMaxTimestamp > resolvedMinTimestamp;
    const x = !hasFixedTimeDomain && normalized.length === 1
      ? width / 2
      : padding + (((point.timestamp - resolvedMinTimestamp) / timestampSpan) * (width - (padding * 2)));
    const y = padding + ((upperBound - point.score) / Math.max(1, upperBound - lowerBound)) * (height - (padding * 2));
    return {
      ...point,
      x: clamp(x, padding, width - padding),
      y: clamp(y, padding, height - padding),
      index,
    };
  });

  return {
    path: buildPath(mappedPoints),
    points: mappedPoints,
    ticks: buildTicks(mappedPoints, width, padding, minTimestamp, maxTimestamp),
    summary,
    showMarkers: false,
  };
}

export function buildPulseFrame({
  latestScore,
  frame,
  width,
  height,
}) {
  const resolvedScore = Number.isFinite(Number(latestScore)) ? Number(latestScore) : 6;
  const baseline = height * 0.58;
  const severity = clamp(resolvedScore, 0, 100);
  const waveAmplitude = 4 + (severity * 0.35);
  const spikeAmplitude = 18 + (severity * 0.8);
  const cycleWidth = 140;
  const step = 6;
  const points = [];

  for (let x = 0; x <= width; x += step) {
    const movingX = x + (frame * step * 0.8);
    const cycle = movingX % cycleWidth;
    const wave = Math.sin(movingX / 14) * waveAmplitude * 0.28;
    let spike = 0;

    if (cycle >= 20 && cycle < 30) {
      spike = -((cycle - 20) / 10) * spikeAmplitude;
    } else if (cycle >= 30 && cycle < 40) {
      spike = -spikeAmplitude + (((cycle - 30) / 10) * spikeAmplitude * 1.7);
    } else if (cycle >= 40 && cycle < 56) {
      spike = (1 - ((cycle - 40) / 16)) * (waveAmplitude * 0.9);
    }

    const y = clamp(baseline + wave + spike, 6, height - 6);
    points.push({ x, y });
  }

  return {
    points,
    path: buildPath(points),
  };
}

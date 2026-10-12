const TREND_KEYS = {
  leg: ['hair_count', 'hair_density_per_mpx'],
  scalp: ['hair_region_fraction_percent', 'texture_fraction_percent'],
};

export function assetPathForRecord(path, manifest) {
  if (typeof path !== 'string' || !Array.isArray(manifest) || !manifest.includes(path)) return null;
  const segments = path.split('/');
  if (segments.length < 2 || segments.some((segment) => !/^[A-Za-z0-9._-]+$/.test(segment) || segment === '.' || segment === '..')) {
    return null;
  }
  return `/api/v1/body-analysis/assets/${segments.map(encodeURIComponent).join('/')}`;
}

export function visibleTrend(report, kind) {
  const section = report?.[kind];
  const keys = TREND_KEYS[kind];
  if (!keys || !Array.isArray(section?.records) || !Array.isArray(section?.trend)) return [];
  const eligibleDates = new Set(section.records
    .filter((record) => record?.trend_eligible === true
      && record.timestamp_verified === true
      && (kind === 'leg' || record.review_status === 'accepted'))
    .map((record) => String(record.captured_at || '').slice(0, 10)));
  return section.trend.filter((item) => {
    if (!item || !eligibleDates.has(item.date)) return false;
    return keys.every((key) => Number.isFinite(item[key]));
  }).map((item) => Object.fromEntries(['date', 'n', ...keys]
    .filter((key) => Object.hasOwn(item, key)).map((key) => [key, item[key]])));
}

export function safeRecordName(value) {
  if (typeof value !== 'string') return '';
  return value.split(/[\\/]/).at(-1) || '';
}

export function formatMetric(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

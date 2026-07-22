function toTimestampMilliseconds(value) {
  if (value instanceof Date) {
    return value.getTime();
  }
  if (typeof value === 'number') {
    return value;
  }
  if (typeof value === 'string') {
    return new Date(value).getTime();
  }
  return Number.NaN;
}
export function buildBrowserLocationQuery(position) {
  const { latitude, longitude, accuracy } = position?.coords ?? {};
  const timestampMs = toTimestampMilliseconds(position?.timestamp);

  if (
    !Number.isFinite(latitude)
    || latitude < -90
    || latitude > 90
    || !Number.isFinite(longitude)
    || longitude < -180
    || longitude > 180
    || !Number.isFinite(accuracy)
    || accuracy <= 0
    || !Number.isFinite(timestampMs)
    || timestampMs <= 0
  ) {
    return '';
  }

  return new URLSearchParams({
    lat: String(latitude),
    lon: String(longitude),
    accuracy: String(accuracy),
    timestamp_ms: String(timestampMs),
  }).toString();
}

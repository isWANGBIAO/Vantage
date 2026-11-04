const UNAVAILABLE = { key: 'dashboard.stat.estimate_unavailable', params: undefined };

// The backend measures completed captures. Do not infer a rate from image
// headers, UI polling intervals, or the size of a partially scanned archive.
export function getStorageForecastPresentation(forecast) {
  if (forecast?.status !== 'ready') {
    return { remaining: UNAVAILABLE, averageCapture: UNAVAILABLE };
  }

  const days = forecast.days_remaining;
  let remaining = UNAVAILABLE;
  if (Number.isFinite(days) && days >= 0) {
    remaining = days > 0 && days < 0.1
      ? { key: 'dashboard.stat.days_left_under_tenth', params: undefined }
      : { key: 'dashboard.stat.days_left', params: { value: days.toFixed(1) } };
  }

  const bytes = forecast.average_capture_bytes;
  const averageCapture = Number.isFinite(bytes) && bytes > 0
    ? { key: 'dashboard.stat.average_capture_size', params: { value: (bytes / (1024 * 1024)).toFixed(2) } }
    : UNAVAILABLE;
  return { remaining, averageCapture };
}

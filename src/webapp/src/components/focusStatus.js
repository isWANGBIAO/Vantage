const DETECTION_STATUSES = ['present', 'absent', 'unknown', 'stale'];

function normalizeNonnegativeNumber(value) {
  return Number.isFinite(value) ? Math.max(0, value) : 0;
}

export function isValidFocusHealthSnapshot(healthStats) {
  return healthStats?.status === 'active'
    && DETECTION_STATUSES.includes(healthStats.detection_status)
    && typeof healthStats.is_sitting === 'boolean'
    && Number.isFinite(healthStats.duration_minutes)
    && healthStats.duration_minutes >= 0
    && Number.isFinite(healthStats.duration_seconds)
    && healthStats.duration_seconds >= 0
    && Number.isFinite(healthStats.threshold_minutes)
    && healthStats.threshold_minutes >= 0;
}

export function degradeFocusHealthSnapshot(previous) {
  return {
    status: 'active',
    detection_status: 'unknown',
    is_sitting: previous?.is_sitting === true,
    duration_minutes: normalizeNonnegativeNumber(previous?.duration_minutes),
    duration_seconds: normalizeNonnegativeNumber(previous?.duration_seconds),
    threshold_minutes: normalizeNonnegativeNumber(previous?.threshold_minutes),
  };
}

export function getFocusStatusPresentation(healthStats) {
  const requestedStatus = healthStats?.detection_status;
  const detectionStatus = DETECTION_STATUSES.includes(requestedStatus)
    ? requestedStatus
    : 'unknown';
  const durationMinutes = Number.isFinite(healthStats?.duration_minutes)
    ? Math.max(0, Math.floor(healthStats.duration_minutes))
    : 0;
  const thresholdMinutes = Number.isFinite(healthStats?.threshold_minutes)
    ? Math.max(0, Math.floor(healthStats.threshold_minutes))
    : 0;
  const isNearLimit = detectionStatus === 'present'
    && thresholdMinutes > 0
    && durationMinutes >= (thresholdMinutes * 0.8);

  let valueKey = 'dashboard.stat.focus_duration';
  let valueParams = { value: durationMinutes };
  let detailKey = 'dashboard.stat.focus_unavailable';
  let detailParams;
  if (detectionStatus === 'present') {
    detailKey = 'dashboard.stat.focus_present';
    detailParams = { value: thresholdMinutes };
  } else if (detectionStatus === 'absent') {
    if (healthStats?.is_sitting === false) {
      valueKey = 'dashboard.stat.away';
      valueParams = undefined;
      detailKey = 'dashboard.stat.focus_absent_confirmed';
    } else {
      detailKey = 'dashboard.stat.focus_absent';
    }
  }

  return {
    detectionStatus,
    valueKey,
    valueParams,
    detailKey,
    detailParams,
    isNearLimit,
  };
}

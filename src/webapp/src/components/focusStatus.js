const DETECTION_STATUSES = ['present', 'absent', 'unknown', 'stale'];
const ACTIVE_TIMERS = ['focus', 'away', 'none'];

function normalizeNonnegativeNumber(value) {
  return Number.isFinite(value) ? Math.max(0, value) : 0;
}

function normalizeActiveTimer(value) {
  return ACTIVE_TIMERS.includes(value) ? value : 'none';
}

export function getDurationPresentation(rawSeconds) {
  const totalSeconds = Math.floor(normalizeNonnegativeNumber(rawSeconds));
  if (totalSeconds < 60) {
    return {
      valueKey: 'dashboard.stat.duration_under_minute',
      valueParams: undefined,
    };
  }

  if (totalSeconds < 3600) {
    return {
      valueKey: 'dashboard.stat.duration_minutes',
      valueParams: { value: Math.floor(totalSeconds / 60) },
    };
  }

  if (totalSeconds < 86400) {
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    if (minutes === 0) {
      return {
        valueKey: 'dashboard.stat.duration_hours',
        valueParams: { value: hours },
      };
    }
    return {
      valueKey: 'dashboard.stat.duration_hours_minutes',
      valueParams: { hours, minutes },
    };
  }

  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  if (hours === 0) {
    return {
      valueKey: days === 1
        ? 'dashboard.stat.duration_days'
        : 'dashboard.stat.duration_days_plural',
      valueParams: { value: days },
    };
  }
  return {
    valueKey: days === 1
      ? 'dashboard.stat.duration_days_hours'
      : 'dashboard.stat.duration_days_hours_plural',
    valueParams: { days, hours },
  };
}

export function isValidFocusHealthSnapshot(healthStats) {
  return healthStats?.status === 'active'
    && DETECTION_STATUSES.includes(healthStats.detection_status)
    && typeof healthStats.is_sitting === 'boolean'
    && Number.isFinite(healthStats.duration_minutes)
    && healthStats.duration_minutes >= 0
    && Number.isFinite(healthStats.duration_seconds)
    && healthStats.duration_seconds >= 0
    && Number.isFinite(healthStats.away_duration_seconds)
    && healthStats.away_duration_seconds >= 0
    && ACTIVE_TIMERS.includes(healthStats.active_timer)
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
    away_duration_seconds: normalizeNonnegativeNumber(previous?.away_duration_seconds),
    active_timer: normalizeActiveTimer(previous?.active_timer),
    threshold_minutes: normalizeNonnegativeNumber(previous?.threshold_minutes),
  };
}

export function getFocusStatusPresentation(healthStats) {
  const requestedStatus = healthStats?.detection_status;
  const detectionStatus = DETECTION_STATUSES.includes(requestedStatus)
    ? requestedStatus
    : 'unknown';
  const focusSeconds = normalizeNonnegativeNumber(healthStats?.duration_seconds);
  const awaySeconds = normalizeNonnegativeNumber(healthStats?.away_duration_seconds);
  const thresholdMinutes = normalizeNonnegativeNumber(healthStats?.threshold_minutes);
  const isNearLimit = detectionStatus === 'present'
    && thresholdMinutes > 0
    && focusSeconds >= (thresholdMinutes * 60 * 0.8);

  let titleKey = 'dashboard.stat.focus_time';
  let displayedSeconds = focusSeconds;
  let detailKey = 'dashboard.stat.focus_unavailable';
  let detailParams;
  if (detectionStatus === 'present') {
    detailKey = 'dashboard.stat.focus_present';
    detailParams = { value: thresholdMinutes };
  } else if (detectionStatus === 'absent') {
    titleKey = 'dashboard.stat.away_time';
    displayedSeconds = awaySeconds;
    if (healthStats?.is_sitting === false) {
      detailKey = 'dashboard.stat.focus_absent_confirmed';
    } else {
      detailKey = 'dashboard.stat.focus_absent';
    }
  } else if (normalizeActiveTimer(healthStats?.active_timer) === 'away') {
    titleKey = 'dashboard.stat.away_time';
    displayedSeconds = awaySeconds;
  } else if (normalizeActiveTimer(healthStats?.active_timer) === 'none') {
    displayedSeconds = 0;
  }

  const { valueKey, valueParams } = getDurationPresentation(displayedSeconds);

  return {
    detectionStatus,
    titleKey,
    valueKey,
    valueParams,
    detailKey,
    detailParams,
    isNearLimit,
  };
}

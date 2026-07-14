export function getFocusStatusPresentation(healthStats) {
  const requestedStatus = healthStats?.detection_status;
  const detectionStatus = ['present', 'absent', 'unknown', 'stale'].includes(requestedStatus)
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

  let detailKey = 'dashboard.stat.focus_unavailable';
  let detailParams;
  if (detectionStatus === 'present') {
    detailKey = 'dashboard.stat.focus_present';
    detailParams = { value: thresholdMinutes };
  } else if (detectionStatus === 'absent') {
    detailKey = 'dashboard.stat.focus_absent';
  }

  return {
    detectionStatus,
    valueKey: 'dashboard.stat.focus_duration',
    valueParams: { value: durationMinutes },
    detailKey,
    detailParams,
    isNearLimit,
  };
}

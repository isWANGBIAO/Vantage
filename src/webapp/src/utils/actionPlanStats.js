const PROVIDER_LABELS = {
  cliproxyapi_primary: 'CLIProxyAPI',
  cliproxyapi_secondary: 'CLIProxyAPI Secondary',
  siliconflow_fallback: 'SiliconFlow',
};

const REASONING_EFFORT_LABELS = {
  default: 'Medium',
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  xhigh: 'Extra High',
  extra_high: 'Extra High',
};

export function formatPoweredByLabel(stats) {
  if (!stats?.model) {
    return null;
  }

  const providerLabel = stats.provider_route
    ? PROVIDER_LABELS[stats.provider_route] || stats.provider_route
    : null;

  return providerLabel ? `${stats.model} · ${providerLabel}` : stats.model;
}

export function formatReasoningEffortLabel(reasoningEffort) {
  if (reasoningEffort === undefined) {
    return null;
  }

  return REASONING_EFFORT_LABELS[reasoningEffort] || reasoningEffort;
}

export function computeDisplayedDurationSeconds(stats, { isActive = false, nowMs = Date.now() } = {}) {
  const backendDuration = Number(stats?.total_duration || 0);
  const startTime = Number(stats?.startTime || 0);

  if (!isActive || !startTime || !Number.isFinite(startTime)) {
    return backendDuration;
  }

  const liveElapsedSeconds = Math.max(0, (nowMs - startTime) / 1000);
  return Math.max(backendDuration, liveElapsedSeconds);
}

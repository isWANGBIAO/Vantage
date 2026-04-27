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
  max: 'Max',
};

export function formatPoweredByLabel(stats) {
  if (!stats?.model) {
    return null;
  }

  const providerLabel = stats.provider_route
    ? stats.provider_label || PROVIDER_LABELS[stats.provider_route] || stats.provider_route
    : null;

  return providerLabel ? `${stats.model} | ${providerLabel}` : stats.model;
}

function normalizeSelectedModelRef(selectedModelRef) {
  const value = selectedModelRef?.current ?? selectedModelRef;
  if (typeof value === 'string') {
    return {
      model: value,
      providerRoute: null,
    };
  }
  if (value && typeof value === 'object') {
    return {
      model: value.model || null,
      providerRoute: value.providerRoute || value.provider_route || null,
    };
  }
  return {
    model: null,
    providerRoute: null,
  };
}

export function isFallbackExecution(stats, selectedModelRef = null) {
  if (!stats) {
    return false;
  }

  if (stats.fallback_used === true) {
    return true;
  }

  const selected = normalizeSelectedModelRef(selectedModelRef);
  const requestedModel = stats.requested_model || selected.model;
  const requestedProviderRoute = stats.requested_provider_route || selected.providerRoute;

  return Boolean(
    (requestedModel && stats.model && requestedModel !== stats.model)
    || (requestedProviderRoute && stats.provider_route && requestedProviderRoute !== stats.provider_route),
  );
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

export function formatCompactTokenValue(value) {
  const number = Number(value || 0);
  if (number >= 1000000) {
    return `${(number / 1000000).toFixed(2)}M`;
  }
  if (number >= 1000) {
    return `${(number / 1000).toFixed(1)}k`;
  }
  return `${Math.round(number)}`;
}

export function formatSecondsValue(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return '-';
  }
  return number.toFixed(1);
}

export function formatActionPlanTokenBreakdown(stats) {
  const totalTokens = Number(stats?.total_tokens || 0);
  const promptTokens = Number(stats?.prompt_tokens || 0);
  const completionTokens = Number(stats?.completion_tokens || 0);
  const totalText = formatCompactTokenValue(totalTokens);

  if (promptTokens <= 0 && completionTokens <= 0) {
    return totalText;
  }

  return `${totalText} (P ${formatCompactTokenValue(promptTokens)} / C ${formatCompactTokenValue(completionTokens)})`;
}

export function getActionPlanRoundStats(stats, section) {
  if (!Array.isArray(stats?.requests)) {
    return null;
  }
  return stats.requests.find((request) => request?.section === section) || null;
}

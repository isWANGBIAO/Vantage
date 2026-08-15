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

const NORMAL_STREAM_FINISH_REASONS = new Set(['stop', 'tool_calls', 'function_call']);

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

function normalizePromptContextWarning(source) {
  if (!source || typeof source !== 'object') {
    return null;
  }

  const warning = source.prompt_context_warning && typeof source.prompt_context_warning === 'object'
    ? source.prompt_context_warning
    : {};
  const limit = Number(
    warning.limit
    ?? source.prompt_token_limit
    ?? 250000,
  );
  const observedPromptTokens = Number(
    warning.observed_prompt_tokens
    ?? source.estimated_prompt_tokens
    ?? source.prompt_tokens,
  );
  const exceeded = source.prompt_token_limit_exceeded === true
    || (
      Number.isFinite(observedPromptTokens)
      && Number.isFinite(limit)
      && observedPromptTokens > limit
    );

  if (!exceeded) {
    return null;
  }

  return {
    limit,
    observedPromptTokens,
    estimated: warning.prompt_tokens === null
      || warning.prompt_tokens === undefined
      || (
        warning.estimated_prompt_tokens !== null
        && warning.estimated_prompt_tokens !== undefined
        && warning.observed_prompt_tokens === warning.estimated_prompt_tokens
      ),
  };
}

export function getActionPlanPromptContextWarning(stats) {
  if (!stats || typeof stats !== 'object') {
    return null;
  }

  if (Array.isArray(stats.requests) && stats.requests.length > 0) {
    const requestWarnings = stats.requests
      .map((request) => normalizePromptContextWarning(request))
      .filter(Boolean);

    if (requestWarnings.length === 0) {
      return null;
    }

    return requestWarnings.sort((left, right) => (
      Number(right.observedPromptTokens || 0) - Number(left.observedPromptTokens || 0)
    ))[0];
  }

  return normalizePromptContextWarning(stats);
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

function hasRecordedUsage(stats) {
  if (!stats) {
    return false;
  }
  if (stats.usage_recorded === false) {
    return false;
  }

  const usageValues = [
    stats.prompt_tokens,
    stats.completion_tokens,
    stats.total_tokens,
    stats.prompt_cache_hit_tokens,
    stats.prompt_cache_miss_tokens,
    stats.completion_reasoning_tokens,
  ];
  return usageValues.some((value) => Number(value) > 0);
}

function normalizeUnrecordedUsageStats(stats) {
  if (!stats || hasRecordedUsage(stats)) {
    return stats;
  }
  return {
    ...stats,
    usage_recorded: false,
    prompt_tokens: null,
    completion_tokens: null,
    total_tokens: null,
    prompt_cache_hit_tokens: null,
    prompt_cache_miss_tokens: null,
    prompt_cache_hit_rate: null,
    completion_reasoning_tokens: null,
    completion_tokens_per_second: null,
    total_tokens_per_second: null,
    output_tokens_per_second: null,
    average_tokens_per_second: null,
  };
}

export function formatSecondsValue(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return '-';
  }
  return number.toFixed(1);
}

export function formatThinkingTitleWithDuration(title, durationSeconds, reasoningTokenCount = null) {
  const baseTitle = String(title ?? '');
  const duration = Number(durationSeconds);
  const reasoningTokens = Number(reasoningTokenCount);
  const hasReasoningTokens = Number.isFinite(reasoningTokens) && reasoningTokens > 0;
  if ((!Number.isFinite(duration) || duration <= 0) && !hasReasoningTokens) {
    return baseTitle;
  }

  const usesLocalizedParentheses = Array.from(baseTitle).some((character) => character.charCodeAt(0) > 127);
  const details = [];
  if (Number.isFinite(duration) && duration > 0) {
    details.push(`${formatSecondsValue(duration)}s`);
  }
  if (hasReasoningTokens) {
    details.push(usesLocalizedParentheses ? `${formatCompactTokenValue(reasoningTokens)} Token` : `${formatCompactTokenValue(reasoningTokens)} tokens`);
  }
  const separator = usesLocalizedParentheses ? '\uFF0C' : ', ';

  return usesLocalizedParentheses
    ? `${baseTitle}\uFF08${details.join(separator)}\uFF09`
    : `${baseTitle} (${details.join(separator)})`;
}

export function formatActionPlanTokenBreakdown(stats) {
  if (!hasRecordedUsage(stats)) {
    return '-';
  }

  const totalTokens = Number(stats?.total_tokens || 0);
  const promptTokens = Number(stats?.prompt_tokens || 0);
  const completionTokens = Number(stats?.completion_tokens || 0);
  const totalText = formatCompactTokenValue(totalTokens);

  if (promptTokens <= 0 && completionTokens <= 0) {
    return totalText;
  }

  return `${totalText} (P ${formatCompactTokenValue(promptTokens)} / C ${formatCompactTokenValue(completionTokens)})`;
}

export function formatActionPlanCacheBreakdown(stats) {
  if (!hasRecordedUsage(stats)) {
    return null;
  }

  const cacheHit = stats?.prompt_cache_hit_tokens;
  const cacheMiss = stats?.prompt_cache_miss_tokens;

  if (cacheHit === null && cacheMiss === null) {
    return null;
  }
  if (cacheHit === undefined && cacheMiss === undefined) {
    return null;
  }

  const hitValue = Number(cacheHit || 0);
  const missValue = Number(cacheMiss || 0);
  const rawRate = stats?.prompt_cache_hit_rate;
  const rate = Number(rawRate);
  const rateText = Number.isFinite(rate) ? ` / ${rate.toFixed(1)}%` : '';
  const shouldShowRate = rawRate !== null && rawRate !== undefined && Number.isFinite(rate);
  return `H ${formatCompactTokenValue(hitValue)} / M ${formatCompactTokenValue(missValue)}${shouldShowRate ? rateText : ''}`;
}

export function getActionPlanRoundNotice(stats, section, content) {
  if (!content || !Array.isArray(stats?.requests)) {
    return null;
  }

  const request = stats.requests.find((item) => item?.section === section);
  if (!request) {
    return null;
  }

  const finishReason = String(request.finish_reason || '').trim().toLowerCase();
  const hasAbnormalFinishReason = Boolean(
    finishReason && !NORMAL_STREAM_FINISH_REASONS.has(finishReason),
  );
  if (request.stream_completed === false || hasAbnormalFinishReason) {
    return 'incomplete';
  }

  const duration = Number(request.duration || 0);
  const hasCompletedRequestEvidence = request.stream_completed === true
    || (Number.isFinite(duration) && duration > 0);
  if (hasCompletedRequestEvidence && !hasRecordedUsage(request)) {
    return 'usage_unavailable';
  }

  return null;
}

export function isActionPlanRoundPossiblyIncomplete(stats, section, content) {
  return getActionPlanRoundNotice(stats, section, content) === 'incomplete';
}

export function getActionPlanRoundStats(stats, section) {
  if (!Array.isArray(stats?.requests)) {
    return null;
  }
  const request = stats.requests.find((item) => item?.section === section) || null;
  return normalizeUnrecordedUsageStats(request);
}

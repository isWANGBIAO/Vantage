import { normalizeActionPlanReasoningEffort } from './actionPlanReasoning.js';

export function buildActionPlanGenerationPayload(reasoningEffort, {
  replaceToday = false,
  model = null,
  providerRoute = null,
} = {}) {
  const payload = {
    reasoning_effort: normalizeActionPlanReasoningEffort(reasoningEffort),
    replace_today: replaceToday,
  };

  if (model) {
    payload.model = model;
  }
  if (providerRoute) {
    payload.provider_route = providerRoute;
  }

  return payload;
}

export function shouldAutogenerateActionPlan({
  hasTriggered,
  isGenerating,
  isAborted,
}) {
  return !hasTriggered && !isGenerating && !isAborted;
}

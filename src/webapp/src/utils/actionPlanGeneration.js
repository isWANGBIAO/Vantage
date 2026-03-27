import { normalizeActionPlanReasoningEffort } from './actionPlanReasoning.js';

export function buildActionPlanGenerationPayload(reasoningEffort, {
  replaceToday = false,
  model = null,
} = {}) {
  const payload = {
    reasoning_effort: normalizeActionPlanReasoningEffort(reasoningEffort),
    replace_today: replaceToday,
  };

  if (model) {
    payload.model = model;
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

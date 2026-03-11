import { normalizeActionPlanReasoningEffort } from './actionPlanReasoning.js';

export function buildActionPlanGenerationPayload(reasoningEffort, { replaceToday = false } = {}) {
  return {
    reasoning_effort: normalizeActionPlanReasoningEffort(reasoningEffort),
    replace_today: replaceToday,
  };
}

export function shouldAutogenerateActionPlan({
  hasTriggered,
  isGenerating,
  isAborted,
}) {
  return !hasTriggered && !isGenerating && !isAborted;
}

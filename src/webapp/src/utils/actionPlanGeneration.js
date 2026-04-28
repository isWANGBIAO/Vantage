import { normalizeReasoningEffortForModel } from './actionPlanReasoning.js';
import { resolveFastServiceTier } from './modelServiceTier.js';

export function buildActionPlanGenerationPayload(reasoningEffort, {
  replaceToday = false,
  model = null,
  providerRoute = null,
  fastModeEnabled = false,
} = {}) {
  const payload = {
    reasoning_effort: normalizeReasoningEffortForModel(reasoningEffort, model),
    replace_today: replaceToday,
  };

  if (model) {
    payload.model = model;
  }
  if (providerRoute) {
    payload.provider_route = providerRoute;
  }
  const serviceTier = resolveFastServiceTier({ fastModeEnabled, model });
  if (serviceTier) {
    payload.service_tier = serviceTier;
  }

  return payload;
}

export function shouldAutogenerateActionPlan({
  autoGenerateEnabled = true,
  hasTriggered,
  isGenerating,
  isAborted,
}) {
  return Boolean(autoGenerateEnabled) && !hasTriggered && !isGenerating && !isAborted;
}

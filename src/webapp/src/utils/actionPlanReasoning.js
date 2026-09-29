export const ACTION_PLAN_REASONING_STORAGE_KEY = 'action_plan_reasoning_effort';

export const ACTION_PLAN_REASONING_OPTIONS = [
  { value: 'low', labelKey: 'common.reasoning.low', fallbackLabel: 'Low' },
  { value: 'medium', labelKey: 'common.reasoning.medium', fallbackLabel: 'Medium' },
  { value: 'high', labelKey: 'common.reasoning.high', fallbackLabel: 'High' },
  { value: 'xhigh', labelKey: 'common.reasoning.xhigh', fallbackLabel: 'Extra High' },
];

const DEEPSEEK_V4_REASONING_OPTIONS = [
  { value: 'high', labelKey: 'common.reasoning.high', fallbackLabel: 'High' },
  { value: 'max', labelKey: 'common.reasoning.max', fallbackLabel: 'Max' },
];

const QWEN38_REASONING_OPTIONS = [
  { value: 'low', labelKey: 'common.reasoning.low', fallbackLabel: 'Low' },
  { value: 'medium', labelKey: 'common.reasoning.medium', fallbackLabel: 'Medium' },
  { value: 'xhigh', labelKey: 'common.reasoning.xhigh', fallbackLabel: 'Extra High' },
];

const VALID_REASONING_EFFORTS = new Set(
  [
    ...ACTION_PLAN_REASONING_OPTIONS,
    ...DEEPSEEK_V4_REASONING_OPTIONS,
  ].map((option) => option.value),
);

// Ordering and aliases used to resolve a level against a model's configured
// tier list. These mirror the backend, which owns the per-model tier lists.
const REASONING_EFFORT_ORDER = ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'];
const REASONING_EFFORT_ALIASES = {
  extra_high: 'xhigh',
  none: 'minimal',
  ultra: 'max',
};

export function isDeepSeekV4Model(model) {
  const normalizedModel = String(model || '').trim().toLowerCase();
  const modelBasename = normalizedModel.split('/').at(-1);
  return modelBasename === 'deepseek-flash'
    || modelBasename === 'deepseek-flash-vision-exp'
    || modelBasename === 'deepseek-v4-flash'
    || modelBasename === 'deepseek-v4-flash-0731';
}

export function isQwen38Model(model) {
  const normalizedModel = String(model || '').trim().toLowerCase();
  return normalizedModel.split('/').at(-1).startsWith('qwen3.8-');
}

export function getReasoningOptionsForModel(model) {
  if (isDeepSeekV4Model(model)) {
    return DEEPSEEK_V4_REASONING_OPTIONS;
  }
  if (isQwen38Model(model)) {
    return QWEN38_REASONING_OPTIONS;
  }
  return ACTION_PLAN_REASONING_OPTIONS;
}

export function normalizeActionPlanReasoningEffort(value) {
  if (VALID_REASONING_EFFORTS.has(value)) {
    return value;
  }
  return 'medium';
}

export function normalizeReasoningEffortForModel(value, model) {
  const normalizedValue = normalizeActionPlanReasoningEffort(value);

  if (isDeepSeekV4Model(model)) {
    return normalizedValue === 'max' ? 'max' : 'high';
  }

  if (isQwen38Model(model)) {
    return ['high', 'xhigh', 'max'].includes(normalizedValue) ? 'xhigh' : normalizedValue;
  }

  return normalizedValue === 'max' ? 'xhigh' : normalizedValue;
}

export function loadStoredActionPlanReasoningEffort(storage = globalThis.localStorage) {
  if (!storage?.getItem) {
    return 'medium';
  }

  return normalizeActionPlanReasoningEffort(
    storage.getItem(ACTION_PLAN_REASONING_STORAGE_KEY),
  );
}

function normalizeReasoningTiers(tiers) {
  if (!Array.isArray(tiers)) {
    return [];
  }
  const normalized = [];
  for (const tier of tiers) {
    const value = String(tier || '').trim().toLowerCase();
    if (value && !normalized.includes(value)) {
      normalized.push(value);
    }
  }
  return normalized;
}

// Display copy for the levels the backend can offer. The list of levels itself
// comes from the provider configuration, so a new level only needs a label
// here, not a rebuild of the resolution logic.
const REASONING_TIER_COPY = {
  minimal: { labelKey: 'common.reasoning.minimal', fallbackLabel: 'Minimal' },
  low: { labelKey: 'common.reasoning.low', fallbackLabel: 'Low' },
  medium: { labelKey: 'common.reasoning.medium', fallbackLabel: 'Medium' },
  high: { labelKey: 'common.reasoning.high', fallbackLabel: 'High' },
  xhigh: { labelKey: 'common.reasoning.xhigh', fallbackLabel: 'Extra High' },
  max: { labelKey: 'common.reasoning.max', fallbackLabel: 'Max' },
};

/**
 * Build the selectable levels from a backend-provided tier list.
 * Unknown levels are still offered, labelled by their own value, so a level
 * added in configuration shows up without a code change.
 */
export function buildReasoningOptionsFromTiers(tiers) {
  return normalizeReasoningTiers(tiers).map((value) => {
    const copy = REASONING_TIER_COPY[value];
    return {
      value,
      labelKey: copy?.labelKey ?? null,
      fallbackLabel: copy?.fallbackLabel ?? value,
    };
  });
}

/**
 * Resolve the effective level for a model from its backend contract.
 * Returns null when the contract is absent, so callers can fall back.
 */
export function resolveReasoningEffortFromContract(tiers, requested, aliases) {
  const candidates = normalizeReasoningTiers(tiers);
  if (candidates.length === 0) {
    return null;
  }
  const normalizedRequested = String(requested || '').trim().toLowerCase();
  // A model profile may declare an intentional remap; that wins over both the
  // requested level itself and the generic ranking rules.
  const declaredAlias = aliases && typeof aliases === 'object'
    ? String(aliases[normalizedRequested] || '').trim().toLowerCase()
    : '';
  if (declaredAlias && candidates.includes(declaredAlias)) {
    return declaredAlias;
  }
  if (candidates.includes(normalizedRequested)) {
    return normalizedRequested;
  }
  const alias = REASONING_EFFORT_ALIASES[normalizedRequested];
  if (alias && candidates.includes(alias)) {
    return alias;
  }
  const rank = REASONING_EFFORT_ORDER.indexOf(alias || normalizedRequested);
  if (rank < 0) {
    return candidates[0];
  }
  const lower = candidates.filter((tier) => {
    const tierRank = REASONING_EFFORT_ORDER.indexOf(tier);
    return tierRank >= 0 && tierRank <= rank;
  });
  if (lower.length === 0) {
    return candidates[0];
  }
  return lower[lower.length - 1];
}

/** Options for a model, using the backend contract when it is available. */
export function getReasoningOptionsForModelContract(model, tiers) {
  const fromContract = buildReasoningOptionsFromTiers(tiers);
  return fromContract.length > 0 ? fromContract : getReasoningOptionsForModel(model);
}

/** Effort for a model, using the backend contract when it is available. */
export function normalizeReasoningEffortForModelContract(value, model, tiers, aliases) {
  const fromContract = resolveReasoningEffortFromContract(tiers, value, aliases);
  return fromContract ?? normalizeReasoningEffortForModel(value, model);
}

export function saveActionPlanReasoningEffort(value, storage = globalThis.localStorage, model = null) {
  const normalizedValue = model
    ? normalizeReasoningEffortForModel(value, model)
    : normalizeActionPlanReasoningEffort(value);

  if (storage?.setItem) {
    storage.setItem(ACTION_PLAN_REASONING_STORAGE_KEY, normalizedValue);
  }

  return normalizedValue;
}

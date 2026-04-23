export const ACTION_PLAN_REASONING_STORAGE_KEY = 'action_plan_reasoning_effort';

export const ACTION_PLAN_REASONING_OPTIONS = [
  { value: 'low', labelKey: 'common.reasoning.low', fallbackLabel: 'Low' },
  { value: 'medium', labelKey: 'common.reasoning.medium', fallbackLabel: 'Medium' },
  { value: 'high', labelKey: 'common.reasoning.high', fallbackLabel: 'High' },
  { value: 'xhigh', labelKey: 'common.reasoning.xhigh', fallbackLabel: 'Extra High' },
];

const VALID_REASONING_EFFORTS = new Set(
  ACTION_PLAN_REASONING_OPTIONS.map((option) => option.value),
);

export function normalizeActionPlanReasoningEffort(value) {
  if (VALID_REASONING_EFFORTS.has(value)) {
    return value;
  }
  return 'medium';
}

export function loadStoredActionPlanReasoningEffort(storage = globalThis.localStorage) {
  if (!storage?.getItem) {
    return 'medium';
  }

  return normalizeActionPlanReasoningEffort(
    storage.getItem(ACTION_PLAN_REASONING_STORAGE_KEY),
  );
}

export function saveActionPlanReasoningEffort(value, storage = globalThis.localStorage) {
  const normalizedValue = normalizeActionPlanReasoningEffort(value);

  if (storage?.setItem) {
    storage.setItem(ACTION_PLAN_REASONING_STORAGE_KEY, normalizedValue);
  }

  return normalizedValue;
}

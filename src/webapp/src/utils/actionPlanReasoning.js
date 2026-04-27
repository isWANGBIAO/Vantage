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

const VALID_REASONING_EFFORTS = new Set(
  [
    ...ACTION_PLAN_REASONING_OPTIONS,
    ...DEEPSEEK_V4_REASONING_OPTIONS,
  ].map((option) => option.value),
);

export function isDeepSeekV4Model(model) {
  const normalizedModel = String(model || '').trim().toLowerCase();
  return normalizedModel === 'deepseek-v4-pro'
    || normalizedModel === 'deepseek-v4-flash'
    || normalizedModel.endsWith('/deepseek-v4-pro')
    || normalizedModel.endsWith('/deepseek-v4-flash');
}

export function getReasoningOptionsForModel(model) {
  return isDeepSeekV4Model(model)
    ? DEEPSEEK_V4_REASONING_OPTIONS
    : ACTION_PLAN_REASONING_OPTIONS;
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
    return ['xhigh', 'max'].includes(normalizedValue) ? 'max' : 'high';
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

export function saveActionPlanReasoningEffort(value, storage = globalThis.localStorage, model = null) {
  const normalizedValue = model
    ? normalizeReasoningEffortForModel(value, model)
    : normalizeActionPlanReasoningEffort(value);

  if (storage?.setItem) {
    storage.setItem(ACTION_PLAN_REASONING_STORAGE_KEY, normalizedValue);
  }

  return normalizedValue;
}

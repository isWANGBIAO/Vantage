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

export function isDeepSeekV4Model(model) {
  const normalizedModel = String(model || '').trim().toLowerCase();
  const modelBasename = normalizedModel.split('/').at(-1);
  return modelBasename === 'deepseek-v4-pro'
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
    return ['xhigh', 'max'].includes(normalizedValue) ? 'max' : 'high';
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

export function saveActionPlanReasoningEffort(value, storage = globalThis.localStorage, model = null) {
  const normalizedValue = model
    ? normalizeReasoningEffortForModel(value, model)
    : normalizeActionPlanReasoningEffort(value);

  if (storage?.setItem) {
    storage.setItem(ACTION_PLAN_REASONING_STORAGE_KEY, normalizedValue);
  }

  return normalizedValue;
}

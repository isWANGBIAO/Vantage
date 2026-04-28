export const FAST_MODE_STORAGE_KEY = 'model_fast_mode_enabled';
export const FAST_SERVICE_TIER_VALUE = 'priority';

const FAST_SERVICE_TIER_MODELS = new Set([
  'gpt-5.5',
  'gpt-5.4',
  'gpt-5.4-mini',
]);

function normalizeModelAlias(model) {
  const normalized = String(model || '').trim().toLowerCase();
  for (const prefix of ['pro/', 'free/']) {
    if (normalized.startsWith(prefix)) {
      return normalized.slice(prefix.length);
    }
  }
  return normalized;
}

export function isFastModeSupportedForModel(model) {
  return FAST_SERVICE_TIER_MODELS.has(normalizeModelAlias(model));
}

export function resolveFastServiceTier({
  fastModeEnabled,
  model,
} = {}) {
  return fastModeEnabled && isFastModeSupportedForModel(model)
    ? FAST_SERVICE_TIER_VALUE
    : null;
}

export function loadStoredFastModeEnabled(storage = globalThis.localStorage) {
  if (!storage?.getItem) {
    return true;
  }

  const storedValue = storage.getItem(FAST_MODE_STORAGE_KEY);
  if (storedValue === null) {
    return true;
  }
  return storedValue !== 'false';
}

export function saveFastModeEnabled(enabled, storage = globalThis.localStorage) {
  const nextValue = Boolean(enabled);
  if (storage?.setItem) {
    storage.setItem(FAST_MODE_STORAGE_KEY, nextValue ? 'true' : 'false');
  }
  return nextValue;
}

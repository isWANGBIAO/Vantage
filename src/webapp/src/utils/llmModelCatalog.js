export const PREFERRED_LLM_MODEL_STORAGE_KEY = 'preferred_llm_model';
export const PREFERRED_LLM_MODEL_REF_STORAGE_KEY = 'preferred_llm_model_ref';

export function buildModelOptionId(providerRoute, model) {
  const normalizedModel = String(model || '').trim();
  const normalizedRoute = String(providerRoute || '').trim();
  return normalizedRoute ? `${normalizedRoute}::${normalizedModel}` : normalizedModel;
}

function normalizeModelOption(rawOption, catalog) {
  const model = String(rawOption?.model || '').trim();
  if (!model) {
    return null;
  }

  const providerRoute = String(rawOption?.provider_route || '').trim();
  const providerLabel = String(rawOption?.provider_label || providerRoute || '').trim();
  const id = String(rawOption?.id || buildModelOptionId(providerRoute, model)).trim();
  const defaultModel = String(catalog?.default_model || '').trim();
  const defaultRoute = String(catalog?.default_provider_route || '').trim();
  const isDefault = Boolean(
    rawOption?.is_default
    || (
      model === defaultModel
      && (!defaultRoute || providerRoute === defaultRoute)
    ),
  );

  return {
    id,
    model,
    provider_route: providerRoute || null,
    provider_label: providerLabel || null,
    label: rawOption?.label || (providerLabel ? `${model} | ${providerLabel}` : model),
    is_default: isDefault,
  };
}

export function buildModelOptionsFromCatalog(catalog) {
  const options = [];
  const seen = new Set();
  const rawOptions = Array.isArray(catalog?.model_options) ? catalog.model_options : [];

  for (const rawOption of rawOptions) {
    const option = normalizeModelOption(rawOption, catalog);
    if (!option || seen.has(option.id)) {
      continue;
    }
    seen.add(option.id);
    options.push(option);
  }

  if (options.length > 0) {
    return options;
  }

  const providers = Array.isArray(catalog?.providers) ? catalog.providers : [];
  for (const provider of providers) {
    const providerRoute = String(provider?.route || '').trim();
    const providerLabel = String(provider?.name || providerRoute || '').trim();
    const models = Array.isArray(provider?.models) ? provider.models : [];
    for (const model of models) {
      const option = normalizeModelOption({
        model,
        provider_route: providerRoute,
        provider_label: providerLabel,
      }, catalog);
      if (!option || seen.has(option.id)) {
        continue;
      }
      seen.add(option.id);
      options.push(option);
    }
  }

  if (options.length > 0) {
    return options;
  }

  const legacyModels = Array.isArray(catalog?.models) ? catalog.models : [];
  for (const model of legacyModels) {
    const option = normalizeModelOption({ model }, catalog);
    if (!option || seen.has(option.id)) {
      continue;
    }
    seen.add(option.id);
    options.push(option);
  }

  return options;
}

export function findModelOption(options, value) {
  const normalizedValue = String(value || '').trim();
  if (!normalizedValue || !Array.isArray(options)) {
    return null;
  }

  return options.find((option) => (
    option.id === normalizedValue
    || option.model === normalizedValue
  )) || null;
}

export function resolvePreferredModelOption(options, storage = globalThis.localStorage) {
  if (!Array.isArray(options) || options.length === 0) {
    return null;
  }

  const storedRef = storage?.getItem?.(PREFERRED_LLM_MODEL_REF_STORAGE_KEY);
  const storedModel = storage?.getItem?.(PREFERRED_LLM_MODEL_STORAGE_KEY);
  return (
    findModelOption(options, storedRef)
    || findModelOption(options, storedModel)
    || options.find((option) => option.is_default)
    || options[0]
  );
}

export function persistPreferredModelOption(option, storage = globalThis.localStorage) {
  if (!option || !storage?.setItem) {
    return;
  }

  storage.setItem(PREFERRED_LLM_MODEL_REF_STORAGE_KEY, option.id);
  storage.setItem(PREFERRED_LLM_MODEL_STORAGE_KEY, option.model);
}

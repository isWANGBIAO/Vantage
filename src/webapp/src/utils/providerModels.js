export function normalizeProviderModels(provider) {
  const seen = new Set();
  const models = [];
  const pushModel = (value) => {
    const normalized = typeof value === 'string' ? value.trim() : '';
    if (!normalized || seen.has(normalized)) {
      return;
    }
    seen.add(normalized);
    models.push(normalized);
  };

  pushModel(provider?.model);
  if (Array.isArray(provider?.models)) {
    provider.models.forEach(pushModel);
  }
  return models;
}

export function normalizeModelList(models, model) {
  return normalizeProviderModels({ model, models });
}

export function resolveInheritedAiProvider(providerConfig) {
  const providers = providerConfig?.providers || {};
  const routes = [...new Set([providerConfig?.selected_provider, ...Object.keys(providers)])];
  const localRoutes = new Set(['custom', 'cliproxyapi', 'cliproxyapi_primary', 'local', 'local_proxy']);
  for (const route of routes) {
    const entry = providers[route];
    if (!entry || entry.enabled === false || !(entry.api_key?.trim() || entry.has_api_key)) continue;
    const baseUrl = entry.base_url?.trim() || (localRoutes.has(route?.toLowerCase()) ? 'http://127.0.0.1:8317/v1' : '');
    if (baseUrl) return { ...entry, route, base_url: baseUrl };
  }
  return null;
}

export function resolveRefreshedModelSelection({
  currentModel,
  currentModels = [],
  discoveredModels = [],
  fallbackModel = '',
}) {
  const normalizedDiscoveredModels = normalizeProviderModels({ models: discoveredModels });
  const normalizedCurrentModel = typeof currentModel === 'string' ? currentModel.trim() : '';

  if (normalizedDiscoveredModels.length > 0) {
    return {
      model: normalizedDiscoveredModels.includes(normalizedCurrentModel)
        ? normalizedCurrentModel
        : normalizedDiscoveredModels[0],
      models: normalizedDiscoveredModels,
    };
  }

  const normalizedCurrentModels = normalizeModelList(currentModels, normalizedCurrentModel || fallbackModel);
  return {
    model: normalizedCurrentModel || normalizedCurrentModels[0] || fallbackModel || '',
    models: normalizedCurrentModels,
  };
}

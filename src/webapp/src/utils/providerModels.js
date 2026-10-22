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

export function resolveInheritedAiProvider(settingsState) {
  // JavaScript reorders integer object keys; it must not reconstruct Python's
  // provider priority. The backend publishes this resolved, credential-free DTO.
  return settingsState?.inheritedAiProvider || null;
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

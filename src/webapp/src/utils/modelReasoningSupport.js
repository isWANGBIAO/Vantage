export function parseModelReasoningSupport(providers = []) {
  const support = {};

  for (const provider of providers) {
    const modelCapabilities = provider?.model_capabilities;
    if (!modelCapabilities || typeof modelCapabilities !== "object") {
      continue;
    }

    for (const [model, rawParams] of Object.entries(modelCapabilities)) {
      if (!model) {
        continue;
      }

      if (!Array.isArray(rawParams)) {
        support[model] = undefined;
        continue;
      }

      const params = rawParams
        .map((item) => String(item || "").trim().toLowerCase().replace(/-/g, "_"))
        .filter(Boolean);

      support[model] = params.some((item) => {
        return item === "reasoning" || item === "reasoning_effort" || item.startsWith("reasoning_");
      });
    }
  }

  return support;
}

export function formatModelReasoningSupportLabel(model, modelReasoningSupport, t) {
  const supported = modelReasoningSupport?.[model];
  if (supported === false) {
    if (typeof t === "function") {
      return t("common.reasoning.unsupported_suffix");
    }
    return "（不支持思考参数）";
  }
  return "";
}

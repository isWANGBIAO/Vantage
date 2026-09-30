// Pure wire-format translation shared by Electron and browser clients.
// Product validation, provider merging, and persistence belong to the backend.
const SETTINGS_PAYLOAD_FIELDS = {
    displayLanguage: 'display_language',
    theme: 'theme',
    themeMode: 'theme_mode',
    launchAtLogin: 'launch_at_login',
    actionPlanAutoGenerate: 'action_plan_auto_generate',
    actionPlanCheckIntervalMinutes: 'action_plan_check_interval_minutes',
    voiceProviderMode: 'voice_provider_mode',
    voiceBaseUrl: 'voice_base_url',
    voiceApiKey: 'voice_api_key',
    voiceModel: 'voice_model',
    voiceModels: 'voice_models',
    voiceLastRefreshedAt: 'voice_last_refreshed_at',
    imageProviderMode: 'image_provider_mode',
    imageBaseUrl: 'image_base_url',
    imageApiKey: 'image_api_key',
    imageModel: 'image_model',
    imageModels: 'image_models',
    imageLastRefreshedAt: 'image_last_refreshed_at',
    providerConfig: 'provider_config',
};
const ONBOARDING_PAYLOAD_FIELDS = {
    displayLanguage: 'display_language',
    launchAtLogin: 'launch_at_login',
    selectedProvider: 'selected_provider',
    baseUrl: 'base_url',
    apiKey: 'api_key',
    model: 'model',
    skipChatSetup: 'skip_chat_setup',
    importLegacyData: 'import_legacy_data',
    legacyRoot: 'legacy_root',
};

function mapPayloadFields(payload, fieldMap) {
    const result = {};
    const source = payload && typeof payload === 'object' ? payload : {};
    for (const [sourceKey, targetKey] of Object.entries(fieldMap)) {
        if (Object.prototype.hasOwnProperty.call(source, sourceKey)) {
            result[targetKey] = source[sourceKey];
        }
    }
    return result;
}

function isJsonCompatibleValue(value, seen = new WeakSet()) {
    if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
    if (typeof value === 'number') return Number.isFinite(value);
    if (typeof value !== 'object' || seen.has(value)) return false;

    const isArray = Array.isArray(value);
    if (!isArray) {
        const prototype = Object.getPrototypeOf(value);
        if (prototype !== Object.prototype && prototype !== null) return false;
    }

    seen.add(value);
    const compatible = isArray
        ? value.every((entry) => isJsonCompatibleValue(entry, seen))
        : Reflect.ownKeys(value).every((key) => (
            typeof key === 'string' && isJsonCompatibleValue(value[key], seen)
        ));
    seen.delete(value);
    return compatible;
}

function isPlainJsonRecord(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
    const prototype = Object.getPrototypeOf(value);
    return (prototype === Object.prototype || prototype === null) && isJsonCompatibleValue(value);
}

function toBackendSettingsPayload(payload) {
    const mapped = mapPayloadFields(payload, SETTINGS_PAYLOAD_FIELDS);
    const providerConfig = mapped.provider_config;
    if (providerConfig && typeof providerConfig === 'object') {
        const providerFields = [
            'route', 'name', 'type', 'enabled', 'api_key', 'base_url', 'model', 'models', 'last_refreshed_at',
            'context_window_tokens',
            'max_output_tokens',
        ];
        const normalizedProviderConfig = { ...providerConfig };
        if (Object.prototype.hasOwnProperty.call(providerConfig, 'providers')) {
            const providers = providerConfig.providers;
            if (providers && typeof providers === 'object' && !Array.isArray(providers)) {
                if (!isPlainJsonRecord(providers)) {
                    throw new TypeError('Provider map must be a plain JSON object.');
                }
                normalizedProviderConfig.providers = Object.fromEntries(
                    Object.entries(providers).map(([route, entry]) => {
                        if (!isPlainJsonRecord(entry)) {
                            throw new TypeError(`Provider entry "${route}" must be a plain JSON object.`);
                        }
                        return [route, Object.fromEntries(providerFields
                            .filter((key) => Object.prototype.hasOwnProperty.call(entry, key))
                            .map((key) => [key, entry[key]]))];
                    }),
                );
            }
        }
        mapped.provider_config = normalizedProviderConfig;
    }
    return mapped;
}

function fromBackendSettings(payload, { mode = 'browser', app = {}, systemLocale = 'en-US' } = {}) {
    if (!isPlainJsonRecord(payload) || !isPlainJsonRecord(payload.settings)) {
        throw new TypeError('Vantage backend returned an invalid settings state.');
    }
    const settings = payload.settings;
    const provider = payload.provider || {};
    return {
        mode,
        settings: {
            displayLanguage: settings.display_language,
            theme: settings.theme,
            themeMode: settings.theme_mode,
            launchAtLogin: settings.launch_at_login,
            actionPlanAutoGenerate: settings.action_plan_auto_generate,
            actionPlanCheckIntervalMinutes: settings.action_plan_check_interval_minutes,
            voiceProviderMode: settings.voice_provider_mode,
            voiceBaseUrl: settings.voice_base_url,
            voiceApiKey: settings.voice_api_key,
            voiceHasApiKey: Boolean(settings.voice_has_api_key),
            voiceModel: settings.voice_model,
            voiceModels: settings.voice_models,
            voiceLastRefreshedAt: settings.voice_last_refreshed_at,
            imageProviderMode: settings.image_provider_mode,
            imageBaseUrl: settings.image_base_url,
            imageApiKey: settings.image_api_key,
            imageHasApiKey: Boolean(settings.image_has_api_key),
            imageModel: settings.image_model,
            imageModels: settings.image_models,
            imageLastRefreshedAt: settings.image_last_refreshed_at,
        },
        provider: {
            ...provider,
            providers: Object.fromEntries(Object.entries(provider.providers || {}).map(([route, entry]) => [
                route,
                { ...entry, has_api_key: entry.api_key === '********' },
            ])),
        },
        runtimePaths: {
            config: payload.runtime_paths?.config_dir,
            history: payload.runtime_paths?.history_dir,
            logs: payload.runtime_paths?.log_dir,
            plots: payload.runtime_paths?.plot_dir,
            cache: payload.runtime_paths?.cache_dir,
            runtime: payload.runtime_paths?.runtime_dir,
            data: payload.runtime_paths?.data_dir,
        },
        migration: {
            completed: payload.migration?.completed === true,
            sourcePath: payload.migration?.source_path || null,
            importedAt: payload.migration?.imported_at || null,
        },
        app: { mode, ...app },
        systemLocale,
    };
}


module.exports = {
    mapPayloadFields,
    toBackendSettingsPayload,
    fromBackendSettings,
    ONBOARDING_PAYLOAD_FIELDS,
};

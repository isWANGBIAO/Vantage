const {
    app,
    BrowserWindow,
    Tray,
    Menu,
    nativeImage,
    nativeTheme,
    ipcMain,
    dialog,
    shell,
    systemPreferences,
    session,
} = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const { resolveRuntimePaths, ensureRuntimeDirs } = require('./src/utils/runtimePaths.cjs');
const { applyLaunchAtLoginSetting } = require('./src/utils/autoLaunch.cjs');
const { ensureBundledBackendReady, terminateBundledBackendProcess } = require('./src/utils/backendRuntime.cjs');
const { resolveAppBuildInfo } = require('./src/utils/buildInfo.cjs');
const { createBoundedLogger } = require('./src/utils/boundedLogger.cjs');
const packageJson = require('./package.json');
let buildInfo = {};
try {
    buildInfo = require('./build-info.json');
} catch {
    buildInfo = {};
}

const projectRoot = path.join(__dirname, '..', '..');
const runtimePaths = resolveRuntimePaths({
    app,
    env: process.env,
    projectRoot,
    platform: process.platform,
});

ensureRuntimeDirs(runtimePaths);

const logsDir = runtimePaths.logDir;
const logFile = path.join(logsDir, `electron_${new Date().toISOString().split('T')[0]}.log`);
let log = {
    info: () => {},
    warn: () => {},
    error: () => {},
};
const isDev = runtimePaths.appMode !== 'packaged' && !app.isPackaged && process.env.NODE_ENV !== 'production';
const shouldManageLoginItem = runtimePaths.appMode === 'packaged' || app.isPackaged;
const BACKEND_HOST = '127.0.0.1';
const BACKEND_PORT = 8000;
const DEFAULT_SETTINGS = {
    display_language: 'system',
    theme: 'dark',
    theme_mode: 'dark',
    launch_at_login: false,
};
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
let canonicalSettings = { ...DEFAULT_SETTINGS };
buildInfo = resolveAppBuildInfo({
    staticBuildInfo: buildInfo,
    projectRoot,
    appMode: runtimePaths.appMode,
    isPackaged: app.isPackaged,
});

const MAIN_PROCESS_COPY = {
    'en-US': {
        trayShowWindow: 'Show Window',
        trayOpenLogs: 'Open Logs Folder',
        trayQuit: 'Quit',
        legacyRootTitle: 'Select Legacy Vantage Source Folder',
        startupErrorTitle: 'Vantage failed to start',
    },
    'zh-CN': {
        trayShowWindow: '显示窗口',
        trayOpenLogs: '打开日志目录',
        trayQuit: '退出',
        legacyRootTitle: '选择旧版 Vantage 源目录',
        startupErrorTitle: 'Vantage 启动失败',
    },
};

let mainWindow = null;
let tray = null;
let bundledBackendProcess = null;
let rendererCameraFramePostInFlight = false;
let rendererCameraFramePostPending = null;

function getTitleBarOverlayOptions(theme = 'dark') {
    const isLight = theme === 'light';

    return {
        color: isLight ? '#ffffff' : '#050508',
        symbolColor: isLight ? '#1a1a2e' : '#f7f7fb',
        height: 64,
    };
}

function requestBackendJson(method, apiPath, payload) {
    if (!apiPath.startsWith('/api/automation/')) {
        return Promise.reject(new Error('Unsupported local backend operation.'));
    }
    const body = payload === undefined ? null : Buffer.from(JSON.stringify(payload), 'utf8');
    return new Promise((resolve, reject) => {
        const request = http.request({
            hostname: BACKEND_HOST,
            port: BACKEND_PORT,
            path: apiPath,
            method,
            headers: body ? {
                'content-type': 'application/json',
                'content-length': body.length,
            } : {},
        }, (response) => {
            const chunks = [];
            let size = 0;
            response.on('data', (chunk) => {
                size += chunk.length;
                if (size > 2 * 1024 * 1024) {
                    request.destroy(new Error('Vantage backend response was too large.'));
                    return;
                }
                chunks.push(chunk);
            });
            response.on('end', () => {
                if (response.statusCode < 200 || response.statusCode >= 300) {
                    reject(new Error(`Vantage backend request failed with status ${response.statusCode}.`));
                    return;
                }
                try {
                    resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
                } catch {
                    reject(new Error('Vantage backend returned an invalid JSON response.'));
                }
            });
        });
        request.setTimeout(10000, () => request.destroy(new Error('Vantage backend request timed out.')));
        request.on('error', (error) => reject(new Error(`Vantage backend request failed: ${error.message}`)));
        if (body) request.write(body);
        request.end();
    });
}

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

function buildElectronSettingsState(payload) {
    const settings = payload.settings || {};
    canonicalSettings = { ...DEFAULT_SETTINGS, ...settings };
    const provider = payload.provider || {};
    return {
        mode: 'electron',
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
        app: {
            version: packageJson.version,
            buildDate: buildInfo.build_date || null,
            buildCommit: buildInfo.build_commit || null,
            mode: runtimePaths.appMode,
            backendRuntimePath: runtimePaths.runtimeDir,
            dataDir: runtimePaths.dataDir,
        },
        systemLocale: app.getLocale(),
    };
}

function sanitizeDisplayLanguage(value) {
    return value === 'zh-CN' || value === 'en-US' || value === 'system' ? value : 'system';
}

function resolveEffectiveThemeForMain(settings = canonicalSettings) {
    const themeMode = settings.theme_mode || settings.theme || 'dark';
    if (themeMode === 'auto') {
        return nativeTheme.shouldUseDarkColors ? 'dark' : 'light';
    }
    return themeMode === 'light' ? 'light' : 'dark';
}

function getWindowChromeOptions() {
    const options = {
        autoHideMenuBar: true,
    };

    if (process.platform === 'win32') {
        options.titleBarStyle = 'hidden';
        options.titleBarOverlay = getTitleBarOverlayOptions(resolveEffectiveThemeForMain());
    }

    return options;
}

const CAMERA_PERMISSION_PRIME_CHANNEL = 'camera:prime-renderer-access';
const CAMERA_PERMISSION_RESULT_CHANNEL = 'camera:renderer-access-result';
const CAMERA_FRAME_BRIDGE_START_CHANNEL = 'camera:start-frame-bridge';
const CAMERA_FRAME_BRIDGE_RESULT_CHANNEL = 'camera:frame-bridge-result';
const CAMERA_FRAME_BRIDGE_ERROR_CHANNEL = 'camera:frame-bridge-error';
const CAMERA_FRAME_CHANNEL = 'camera:renderer-frame';
const RENDERER_CAMERA_FRAME_INTENT = 'renderer-camera-frame';
const RENDERER_CAMERA_MAX_FRAME_BYTES = 8 * 1024 * 1024;

function mapLocaleToSupportedLanguage(locale) {
    return typeof locale === 'string' && locale.trim().toLowerCase().startsWith('zh')
        ? 'zh-CN'
        : 'en-US';
}

function getEffectiveDisplayLanguageForMain() {
    const displayLanguage = sanitizeDisplayLanguage(canonicalSettings.display_language);
    return displayLanguage === 'system'
        ? mapLocaleToSupportedLanguage(app.getLocale())
        : displayLanguage;
}

function getMainProcessCopy() {
    const language = getEffectiveDisplayLanguageForMain();
    return MAIN_PROCESS_COPY[language] || MAIN_PROCESS_COPY['en-US'];
}

function openMacosCameraPrivacySettings(reason) {
    if (process.platform !== 'darwin') {
        return;
    }

    const privacyUrl = 'x-apple.systempreferences:com.apple.preference.security?Privacy_Camera';
    shell.openExternal(privacyUrl)
        .then(() => {
            log.warn(`Opened macOS camera privacy settings: ${reason}`);
        })
        .catch((error) => {
            log.warn(`Failed to open macOS camera privacy settings: ${error.message}`);
        });
}

function configureMediaPermissionHandler() {
    if (process.platform !== 'darwin' || !session?.defaultSession?.setPermissionRequestHandler) {
        return;
    }

    session.defaultSession.setPermissionRequestHandler((webContents, permission, callback, details = {}) => {
        const isMainWindowRequest = Boolean(mainWindow && webContents === mainWindow.webContents);
        const requestedMediaTypes = Array.isArray(details.mediaTypes) ? details.mediaTypes : [];
        const isCameraMediaRequest = permission === 'media'
            && (requestedMediaTypes.length === 0 || requestedMediaTypes.includes('video'));

        if (isMainWindowRequest && isCameraMediaRequest) {
            log.info('Approved renderer media permission request for camera priming');
            callback(true);
            return;
        }

        callback(false);
    });
}

function waitForMainWindowLoad({ timeoutMs = 3000 } = {}) {
    if (!mainWindow || !mainWindow.webContents || typeof mainWindow.webContents.isLoading !== 'function') {
        return Promise.resolve(false);
    }

    if (!mainWindow.webContents.isLoading()) {
        return Promise.resolve(true);
    }

    return new Promise((resolve) => {
        let settled = false;

        const finish = (loaded) => {
            if (settled) {
                return;
            }
            settled = true;
            clearTimeout(timer);
            mainWindow?.webContents?.off('did-finish-load', onFinishLoad);
            mainWindow?.webContents?.off('did-fail-load', onFailLoad);
            resolve(loaded);
        };

        const onFinishLoad = () => finish(true);
        const onFailLoad = () => finish(false);
        const timer = setTimeout(() => finish(false), timeoutMs);

        mainWindow.webContents.once('did-finish-load', onFinishLoad);
        mainWindow.webContents.once('did-fail-load', onFailLoad);
    });
}

async function requestRendererCameraAccess({ timeoutMs = 5000 } = {}) {
    if (process.platform !== 'darwin' || !mainWindow || !mainWindow.webContents) {
        return null;
    }

    await waitForMainWindowLoad({ timeoutMs: Math.min(timeoutMs, 3000) });

    return new Promise((resolve) => {
        let settled = false;

        const finish = (result) => {
            if (settled) {
                return;
            }
            settled = true;
            clearTimeout(timer);
            ipcMain.off(CAMERA_PERMISSION_RESULT_CHANNEL, onRendererResult);
            resolve(result);
        };

        const onRendererResult = (event, result = {}) => {
            if (event.sender !== mainWindow?.webContents) {
                return;
            }

            const granted = result?.granted === true;
            const errorMessage = typeof result?.error === 'string' ? result.error : null;
            log.info(`Renderer camera access result: ${JSON.stringify({ granted, error: errorMessage })}`);
            finish(granted);
        };

        const timer = setTimeout(() => {
            log.warn('Renderer camera access request timed out; continuing backend startup');
            finish(null);
        }, timeoutMs);

        ipcMain.on(CAMERA_PERMISSION_RESULT_CHANNEL, onRendererResult);
        log.info('Requesting renderer camera access priming');
        mainWindow.webContents.send(CAMERA_PERMISSION_PRIME_CHANNEL);
    });
}

async function requestMacosCameraAccess({ timeoutMs = 5000 } = {}) {
    if (process.platform !== 'darwin') {
        return null;
    }

    if (typeof systemPreferences.getMediaAccessStatus === 'function') {
        const status = systemPreferences.getMediaAccessStatus('camera');
        log.info(`macOS camera permission status: ${status}`);
        if (status === 'granted') {
            return true;
        }
        if (status === 'denied' || status === 'restricted') {
            openMacosCameraPrivacySettings(status);
            return false;
        }
    }

    const rendererAccess = await requestRendererCameraAccess({ timeoutMs });

    if (typeof systemPreferences.askForMediaAccess !== 'function') {
        return rendererAccess;
    }

    if (rendererAccess === true) {
        log.info('Renderer camera access granted; confirming macOS camera media access');
    }

    const accessRequest = systemPreferences.askForMediaAccess('camera')
        .then((granted) => {
            log.info(`macOS camera permission ${granted ? 'granted' : 'not granted'}`);
            return granted;
        })
        .catch((error) => {
            log.warn(`macOS camera permission request failed: ${error.message}`);
            return false;
        });

    const timeout = new Promise((resolve) => {
        setTimeout(() => {
            log.warn('macOS camera permission request still pending; continuing backend startup');
            openMacosCameraPrivacySettings('request pending');
            resolve(null);
        }, timeoutMs);
    });

    const confirmedAccess = await Promise.race([accessRequest, timeout]);
    return confirmedAccess === null ? rendererAccess : Boolean(confirmedAccess || rendererAccess === true);
}

function postRendererCameraFrame(frameBytes) {
    let frameBuffer = null;
    try {
        frameBuffer = Buffer.isBuffer(frameBytes) ? frameBytes : Buffer.from(frameBytes);
    } catch {
        return;
    }

    if (!frameBuffer.length || frameBuffer.length > RENDERER_CAMERA_MAX_FRAME_BYTES) {
        return;
    }

    if (rendererCameraFramePostInFlight) {
        rendererCameraFramePostPending = frameBuffer;
        return;
    }

    rendererCameraFramePostInFlight = true;
    let settled = false;

    const finish = () => {
        if (settled) {
            return;
        }
        settled = true;
        rendererCameraFramePostInFlight = false;
        if (rendererCameraFramePostPending) {
            const pendingFrame = rendererCameraFramePostPending;
            rendererCameraFramePostPending = null;
            setImmediate(() => postRendererCameraFrame(pendingFrame));
        }
    };

    const request = http.request(
        {
            hostname: '127.0.0.1',
            port: 8000,
            path: '/api/renderer_camera/frame',
            method: 'POST',
            timeout: 3000,
            headers: {
                'content-type': 'image/jpeg',
                'content-length': frameBuffer.length,
                'x-vantage-intent': RENDERER_CAMERA_FRAME_INTENT,
            },
        },
        (response) => {
            response.resume();
            response.on('end', finish);
        },
    );

    request.on('timeout', () => {
        request.destroy(new Error('Renderer camera frame post timed out'));
    });
    request.on('error', finish);
    request.write(frameBuffer);
    request.end();
}

async function startRendererCameraFrameBridge({ intervalMs = 500 } = {}) {
    if (process.platform !== 'darwin' || !mainWindow || !mainWindow.webContents) {
        return;
    }

    await waitForMainWindowLoad({ timeoutMs: 3000 });
    log.info('Starting renderer camera frame bridge');
    mainWindow.webContents.send(CAMERA_FRAME_BRIDGE_START_CHANNEL, {
        intervalMs,
        width: 1280,
        height: 720,
        quality: 0.82,
    });
}

const settingsPathAllowlist = {
    config: () => runtimePaths.configDir,
    history: () => runtimePaths.historyDir,
    logs: () => runtimePaths.logDir,
    plots: () => runtimePaths.plotDir,
    cache: () => runtimePaths.cacheDir,
    runtime: () => runtimePaths.runtimeDir,
    data: () => runtimePaths.dataDir,
};

function resolveAllowedSettingsPath(pathKey) {
    const resolver = settingsPathAllowlist[pathKey];
    if (!resolver) {
        return null;
    }

    const resolvedPath = path.resolve(resolver());
    const allowedPaths = Object.values(settingsPathAllowlist).map((entry) => path.resolve(entry()));
    return allowedPaths.includes(resolvedPath) ? resolvedPath : null;
}

async function getSettingsStatePayload() {
    return buildElectronSettingsState(await requestBackendJson('GET', '/api/automation/settings'));
}

function syncTrayMenu() {
    if (!tray) {
        return;
    }

    const copy = getMainProcessCopy();
    const contextMenu = Menu.buildFromTemplate([
        {
            label: copy.trayShowWindow,
            click: () => {
                mainWindow?.show();
                mainWindow?.focus();
                log.info('Window restored from tray');
            },
        },
        { type: 'separator' },
        {
            label: copy.trayOpenLogs,
            click: () => {
                void shell.openPath(logsDir);
            },
        },
        { type: 'separator' },
        {
            label: copy.trayQuit,
            click: () => {
                log.info('User requested quit from tray');
                app.isQuitting = true;
                app.quit();
            },
        },
    ]);

    tray.setToolTip('Vantage');
    tray.setContextMenu(contextMenu);
}

async function syncLaunchAtLoginSetting() {
    if (!shouldManageLoginItem) {
        log.info('Launch-at-login management skipped outside packaged installs');
        return null;
    }

    const settingsPayload = await requestBackendJson('GET', '/api/automation/settings');
    const state = buildElectronSettingsState(settingsPayload);
    const enabled = applyLaunchAtLoginSetting({ app, enabled: state.settings.launchAtLogin });
    log.info(`Launch at login ${enabled ? 'enabled' : 'disabled'} from saved settings`);
    return state;
}

process.on('uncaughtException', (error) => {
    log.error('Uncaught Exception', error);
});

process.on('unhandledRejection', (reason, promise) => {
    log.error(`Unhandled Rejection at: ${promise}, reason: ${reason}`);
});

ipcMain.handle('onboarding:get-state', async () => requestBackendJson('GET', '/api/automation/onboarding'));

ipcMain.handle('settings:get-state', async () => getSettingsStatePayload());

ipcMain.on(CAMERA_FRAME_CHANNEL, (event, frameBytes) => {
    if (event.sender !== mainWindow?.webContents) {
        return;
    }
    postRendererCameraFrame(frameBytes);
});

ipcMain.on(CAMERA_FRAME_BRIDGE_RESULT_CHANNEL, (event, result = {}) => {
    if (event.sender !== mainWindow?.webContents) {
        return;
    }

    if (result.started) {
        const mode = typeof result.mode === 'string' ? result.mode : 'unknown';
        log.info(`Renderer camera frame bridge ${result.reused ? 'reused' : 'started'} (${mode})`);
    } else {
        const errorMessage = typeof result.error === 'string' ? result.error : 'unknown error';
        log.warn(`Renderer camera frame bridge failed: ${errorMessage}`);
    }
});

ipcMain.on(CAMERA_FRAME_BRIDGE_ERROR_CHANNEL, (event, result = {}) => {
    if (event.sender !== mainWindow?.webContents) {
        return;
    }

    const errorMessage = typeof result.error === 'string' ? result.error : 'unknown error';
    log.warn(`Renderer camera frame capture failed: ${errorMessage}`);
});

ipcMain.handle('settings:save', async (event, payload) => {
    const response = await requestBackendJson(
        'PUT',
        '/api/automation/settings',
        toBackendSettingsPayload(payload),
    );
    const state = buildElectronSettingsState(response);

    if (shouldManageLoginItem) {
        applyLaunchAtLoginSetting({
            app,
            enabled: state.settings.launchAtLogin,
        });
        log.info(`Launch at login ${state.settings.launchAtLogin ? 'enabled' : 'disabled'} from settings`);
    } else {
        log.info('Launch-at-login settings save skipped outside packaged installs');
    }

    syncTrayMenu();
    if (mainWindow && process.platform === 'win32' && typeof mainWindow.setTitleBarOverlay === 'function') {
        mainWindow.setTitleBarOverlay(getTitleBarOverlayOptions(resolveEffectiveThemeForMain()));
    }
    return state;
});

ipcMain.handle('settings:open-path', async (event, pathKey) => {
    const targetPath = resolveAllowedSettingsPath(pathKey);
    if (!targetPath) {
        return { opened: false, error: 'Path is not allowed.' };
    }

    fs.mkdirSync(targetPath, { recursive: true });
    const error = await shell.openPath(targetPath);
    return {
        opened: !error,
        path: targetPath,
        error: error || null,
    };
});

ipcMain.handle('onboarding:pick-legacy-root', async () => {
    const copy = getMainProcessCopy();
    const result = await dialog.showOpenDialog({
        properties: ['openDirectory'],
        title: copy.legacyRootTitle,
    });

    return {
        path: result.canceled ? null : (result.filePaths[0] || null),
    };
});

ipcMain.handle('settings:get-display-language-state', async () => {
    const settings = await requestBackendJson('GET', '/api/automation/settings/display-language');
    canonicalSettings.display_language = settings.display_language;
    return {
        displayLanguage: sanitizeDisplayLanguage(settings.display_language),
        systemLocale: app.getLocale(),
    };
});

ipcMain.handle('settings:set-display-language', async (event, displayLanguage) => {
    const nextDisplayLanguage = sanitizeDisplayLanguage(displayLanguage);
    const settings = await requestBackendJson(
        'PUT',
        '/api/automation/settings/display-language',
        { display_language: nextDisplayLanguage },
    );
    canonicalSettings.display_language = settings.display_language;
    syncTrayMenu();

    return {
        displayLanguage: settings.display_language,
        systemLocale: app.getLocale(),
    };
});

ipcMain.handle('settings:get-system-locale', async () => app.getLocale());

ipcMain.handle('window:set-title-bar-theme', async (event, theme) => {
    const sourceWindow = BrowserWindow.fromWebContents(event.sender);
    if (!sourceWindow || process.platform !== 'win32' || typeof sourceWindow.setTitleBarOverlay !== 'function') {
        return { applied: false };
    }

    sourceWindow.setTitleBarOverlay(getTitleBarOverlayOptions(theme === 'light' ? 'light' : 'dark'));
    return { applied: true };
});

ipcMain.handle('onboarding:complete', async (event, submission) => {
    const result = await requestBackendJson(
        'POST',
        '/api/automation/onboarding/complete',
        mapPayloadFields(submission, ONBOARDING_PAYLOAD_FIELDS),
    );
    canonicalSettings = { ...canonicalSettings, ...(result.settings || {}) };

    if (shouldManageLoginItem) {
        applyLaunchAtLoginSetting({
            app,
            enabled: result.launchAtLogin,
        });
        log.info(`Launch at login ${result.launchAtLogin ? 'enabled' : 'disabled'} from onboarding`);
    }

    syncTrayMenu();
    return result;
});

function createWindow() {
    log.info('Creating main window...');

    mainWindow = new BrowserWindow({
        width: 1400,
        height: 900,
        minWidth: 1000,
        minHeight: 700,
        webPreferences: {
            preload: path.join(__dirname, 'preload.cjs'),
            contextIsolation: true,
            nodeIntegration: false,
        },
        icon: path.join(__dirname, '..', '..', 'icon.png'),
        title: 'Vantage',
        backgroundColor: '#050508',
        show: false,
        ...getWindowChromeOptions(),
    });

    if (isDev) {
        log.info('Loading Vite dev server: http://localhost:5173');
        void mainWindow.loadURL('http://localhost:5173');
        mainWindow.webContents.openDevTools();
    } else {
        const indexPath = path.join(__dirname, 'dist', 'index.html');
        log.info(`Loading production build: ${indexPath}`);
        void mainWindow.loadFile(indexPath);
    }

    mainWindow.once('ready-to-show', () => {
        log.info('Window ready, showing...');
        mainWindow.maximize();
        mainWindow.show();
    });

    mainWindow.webContents.on('crashed', (event, killed) => {
        log.error(`Renderer process crashed (killed: ${killed})`);
    });

    mainWindow.webContents.on('render-process-gone', (event, details) => {
        log.error(`Renderer process gone: ${details.reason}`);
    });

    mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDesc, validatedURL) => {
        log.error(`Failed to load URL: ${validatedURL}, Error: ${errorCode} - ${errorDesc}`);
    });

    mainWindow.on('close', (event) => {
        if (!app.isQuitting) {
            event.preventDefault();
            mainWindow.hide();
            log.info('Window hidden to tray');
        }
    });
}

function createTray() {
    log.info('Creating system tray...');
    const iconPath = path.join(__dirname, '..', '..', 'icon.png');
    const icon = nativeImage.createFromPath(iconPath);

    tray = new Tray(icon.resize({ width: 16, height: 16 }));
    syncTrayMenu();

    tray.on('double-click', () => {
        mainWindow?.show();
        mainWindow?.focus();
        log.info('Window restored via tray double-click');
    });
}

const gotTheLock = app.requestSingleInstanceLock();

if (!gotTheLock) {
    app.quit();
} else {
    log = createBoundedLogger({
        logFile,
        consoleObject: console,
        stdout: process.stdout,
        stderr: process.stderr,
        pathPrefixes: [
            { prefix: app.getPath('home'), label: '<user-home>' },
            { prefix: app.getPath('userData'), label: '<user-data>' },
            { prefix: runtimePaths.dataDir, label: '<runtime-data>' },
            { prefix: runtimePaths.logDir, label: '<runtime-logs>' },
            { prefix: __dirname, label: '<app-root>' },
            { prefix: projectRoot, label: '<project-root>' },
            {
                prefix: path.dirname(process.execPath),
                label: '<app-executable>',
            },
        ],
    });
    log.cleanup();
    log.info('Vantage Electron starting...');
    log.info(`Mode: ${isDev ? 'Development' : 'Production'}`);
    log.info(`Log file: ${logFile}`);
    log.info(`Runtime data dir: ${runtimePaths.dataDir}`);

    app.on('second-instance', () => {
        log.info('Second instance detected, focusing existing window');
        if (mainWindow) {
            if (mainWindow.isMinimized()) {
                mainWindow.restore();
            }
            mainWindow.show();
            mainWindow.focus();
        }
    });

    app.whenReady().then(async () => {
        log.info('App ready, initializing...');
        Menu.setApplicationMenu(null);
        configureMediaPermissionHandler();

        const shouldLaunchBundledBackend = runtimePaths.appMode === 'packaged' || app.isPackaged;
        createWindow();
        createTray();

        if (shouldLaunchBundledBackend) {
            await requestMacosCameraAccess();

            try {
                const backendBootstrap = await ensureBundledBackendReady({
                    isDev: false,
                    runtimePaths,
                    env: process.env,
                    resourcesPath: process.resourcesPath,
                    platform: process.platform,
                    logger: log,
                });
                bundledBackendProcess = backendBootstrap.process;
                log.info(
                    backendBootstrap.started
                        ? `Bundled backend started: ${backendBootstrap.executablePath}`
                        : `Bundled backend reused: ${backendBootstrap.reason}`,
                );
                try {
                    await syncLaunchAtLoginSetting();
                    syncTrayMenu();
                    if (mainWindow && process.platform === 'win32' && typeof mainWindow.setTitleBarOverlay === 'function') {
                        mainWindow.setTitleBarOverlay(getTitleBarOverlayOptions(resolveEffectiveThemeForMain()));
                    }
                } catch (error) {
                    log.warn(`Failed to load shared settings from backend: ${error.message}`);
                }
                await startRendererCameraFrameBridge();
            } catch (error) {
                log.error('Bundled backend startup failed', error);
                dialog.showErrorBox(
                    getMainProcessCopy().startupErrorTitle,
                    `Bundled backend startup failed.\n\n${error.message}`,
                );
                app.exit(1);
                return;
            }
        } else {
            log.info('Development Electron flow detected, backend launch remains external');
        }

        app.on('activate', () => {
            if (BrowserWindow.getAllWindows().length === 0) {
                createWindow();
            }
        });
    });
}

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        log.info('All windows closed, quitting app');
        app.quit();
    }
});

app.on('before-quit', () => {
    log.info('App quitting...');
    app.isQuitting = true;
    terminateBundledBackendProcess(bundledBackendProcess, {
        platform: process.platform,
        logger: log,
    });
});

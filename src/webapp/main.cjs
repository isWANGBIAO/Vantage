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
const {
    buildSettingsState,
    getOnboardingState,
    loadSettings,
    saveSettingsPayload,
    saveOnboardingCompletion,
    sanitizeDisplayLanguage,
} = require('./src/utils/onboardingConfig.cjs');
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
const isDev = runtimePaths.appMode !== 'packaged' && !app.isPackaged && process.env.NODE_ENV !== 'production';
const shouldManageLoginItem = runtimePaths.appMode === 'packaged' || app.isPackaged;

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

function resolveEffectiveThemeForMain(settings = loadSettings(runtimePaths)) {
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

function writeLog(level, message, error = null) {
    const timestamp = new Date().toISOString();
    let logEntry = `[${timestamp}] [${level}] ${message}`;

    if (error) {
        logEntry += `\n  Stack: ${error.stack || error}`;
    }

    logEntry += '\n';
    fs.appendFileSync(logFile, logEntry);

    if (level === 'ERROR') {
        console.error(logEntry);
    } else {
        console.log(logEntry);
    }
}

const log = {
    info: (message) => writeLog('INFO', message),
    warn: (message) => writeLog('WARN', message),
    error: (message, error = null) => writeLog('ERROR', message, error),
};

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
    const settings = loadSettings(runtimePaths);
    const displayLanguage = sanitizeDisplayLanguage(settings.display_language);
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
            if (rendererAccess !== true) {
                openMacosCameraPrivacySettings('request pending');
            }
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

function persistSettings(nextSettings) {
    const settingsFile = path.join(runtimePaths.configDir, 'settings.json');
    fs.mkdirSync(runtimePaths.configDir, { recursive: true });
    fs.writeFileSync(settingsFile, JSON.stringify(nextSettings, null, 2), 'utf8');
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

function getSettingsStatePayload() {
    return buildSettingsState({
        runtimePaths,
        projectRoot,
        appVersion: packageJson.version,
        appBuildInfo: buildInfo,
        appMode: runtimePaths.appMode,
        systemLocale: app.getLocale(),
    });
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

function syncLaunchAtLoginSetting() {
    const onboardingState = getOnboardingState({ runtimePaths, projectRoot });

    if (!shouldManageLoginItem) {
        log.info('Launch-at-login management skipped outside packaged installs');
        return onboardingState;
    }

    const enabled = applyLaunchAtLoginSetting({
        app,
        enabled: onboardingState.launchAtLogin,
    });
    log.info(`Launch at login ${enabled ? 'enabled' : 'disabled'} from saved settings`);
    return onboardingState;
}

process.on('uncaughtException', (error) => {
    log.error('Uncaught Exception', error);
});

process.on('unhandledRejection', (reason, promise) => {
    log.error(`Unhandled Rejection at: ${promise}, reason: ${reason}`);
});

ipcMain.handle('onboarding:get-state', async () => getOnboardingState({ runtimePaths, projectRoot }));

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
    const state = saveSettingsPayload({
        runtimePaths,
        payload: payload || {},
        projectRoot,
        appVersion: packageJson.version,
        appBuildInfo: buildInfo,
        appMode: runtimePaths.appMode,
        systemLocale: app.getLocale(),
    });

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
    const settings = loadSettings(runtimePaths);
    return {
        displayLanguage: sanitizeDisplayLanguage(settings.display_language),
        systemLocale: app.getLocale(),
    };
});

ipcMain.handle('settings:set-display-language', async (event, displayLanguage) => {
    const settings = loadSettings(runtimePaths);
    const nextDisplayLanguage = sanitizeDisplayLanguage(displayLanguage);
    persistSettings({
        ...settings,
        display_language: nextDisplayLanguage,
    });
    syncTrayMenu();

    return {
        displayLanguage: nextDisplayLanguage,
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
    const result = saveOnboardingCompletion({
        runtimePaths,
        submission: submission || {},
        projectRoot,
    });

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

log.info('Vantage Electron starting...');
log.info(`Mode: ${isDev ? 'Development' : 'Production'}`);
log.info(`Log file: ${logFile}`);
log.info(`Runtime data dir: ${runtimePaths.dataDir}`);

if (!gotTheLock) {
    log.warn('Another instance is already running. Quitting this instance.');
    app.quit();
} else {
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
        syncLaunchAtLoginSetting();

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

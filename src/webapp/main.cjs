const {
    app,
    BrowserWindow,
    Tray,
    Menu,
    nativeImage,
    ipcMain,
    dialog,
    shell,
} = require('electron');
const path = require('path');
const fs = require('fs');
const { resolveRuntimePaths, ensureRuntimeDirs } = require('./src/utils/runtimePaths.cjs');
const { applyLaunchAtLoginSetting } = require('./src/utils/autoLaunch.cjs');
const { ensureBundledBackendReady, terminateBundledBackendProcess } = require('./src/utils/backendRuntime.cjs');
const {
    getOnboardingState,
    loadSettings,
    saveOnboardingCompletion,
    sanitizeDisplayLanguage,
} = require('./src/utils/onboardingConfig.cjs');

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

function persistSettings(nextSettings) {
    const settingsFile = path.join(runtimePaths.configDir, 'settings.json');
    fs.mkdirSync(runtimePaths.configDir, { recursive: true });
    fs.writeFileSync(settingsFile, JSON.stringify(nextSettings, null, 2), 'utf8');
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
        syncLaunchAtLoginSetting();

        const shouldLaunchBundledBackend = runtimePaths.appMode === 'packaged' || app.isPackaged;
        if (shouldLaunchBundledBackend) {
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

        createWindow();
        createTray();

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

const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const { resolveRuntimePaths, ensureRuntimeDirs } = require('./src/utils/runtimePaths.cjs');
const { getOnboardingState } = require('./src/utils/onboardingConfig.cjs');

// ============ 日志系统 ============
const runtimePaths = resolveRuntimePaths({
    app,
    env: process.env,
    projectRoot: path.join(__dirname, '..', '..'),
    platform: process.platform,
});
ensureRuntimeDirs(runtimePaths);
const logsDir = runtimePaths.logDir;

const logFile = path.join(logsDir, `electron_${new Date().toISOString().split('T')[0]}.log`);

function writeLog(level, message, error = null) {
    const timestamp = new Date().toISOString();
    let logEntry = `[${timestamp}] [${level}] ${message}`;
    if (error) {
        logEntry += `\n  Stack: ${error.stack || error}`;
    }
    logEntry += '\n';

    // 写入文件
    fs.appendFileSync(logFile, logEntry);

    // 同时输出到控制台
    if (level === 'ERROR') {
        console.error(logEntry);
    } else {
        console.log(logEntry);
    }
}

const log = {
    info: (msg) => writeLog('INFO', msg),
    warn: (msg) => writeLog('WARN', msg),
    error: (msg, err = null) => writeLog('ERROR', msg, err)
};

// ============ 全局异常捕获 ============
process.on('uncaughtException', (error) => {
    log.error('Uncaught Exception', error);
});

process.on('unhandledRejection', (reason, promise) => {
    log.error(`Unhandled Rejection at: ${promise}, reason: ${reason}`);
});

// ============ Electron 应用 ============
const isDev = runtimePaths.appMode !== 'packaged' && !app.isPackaged && process.env.NODE_ENV !== 'production';

let mainWindow = null;
let tray = null;

log.info('Vantage Electron starting...');
log.info(`Mode: ${isDev ? 'Development' : 'Production'}`);
log.info(`Log file: ${logFile}`);
log.info(`Runtime data dir: ${runtimePaths.dataDir}`);

ipcMain.handle('onboarding:get-state', async () => getOnboardingState({ runtimePaths }));

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
            nodeIntegration: false
        },
        icon: path.join(__dirname, '..', '..', 'icon.png'),
        title: 'Vantage',
        backgroundColor: '#050508',
        show: false
    });

    // 加载应用
    if (isDev) {
        log.info('Loading Vite dev server: http://localhost:5173');
        mainWindow.loadURL('http://localhost:5173');
        mainWindow.webContents.openDevTools();
    } else {
        const indexPath = path.join(__dirname, 'dist', 'index.html');
        log.info(`Loading production build: ${indexPath}`);
        mainWindow.loadFile(indexPath);
    }

    // 窗口准备好后显示
    mainWindow.once('ready-to-show', () => {
        log.info('Window ready, showing...');
        mainWindow.maximize();
        mainWindow.show();
    });

    // 渲染进程错误捕获
    mainWindow.webContents.on('crashed', (event, killed) => {
        log.error(`Renderer process crashed (killed: ${killed})`);
    });

    mainWindow.webContents.on('render-process-gone', (event, details) => {
        log.error(`Renderer process gone: ${details.reason}`);
    });

    mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDesc, validatedURL) => {
        log.error(`Failed to load URL: ${validatedURL}, Error: ${errorCode} - ${errorDesc}`);
    });

    // 最小化到托盘而非关闭
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

    const contextMenu = Menu.buildFromTemplate([
        {
            label: '显示窗口',
            click: () => {
                mainWindow.show();
                mainWindow.focus();
                log.info('Window restored from tray');
            }
        },
        { type: 'separator' },
        {
            label: '打开日志目录',
            click: () => {
                require('electron').shell.openPath(logsDir);
            }
        },
        { type: 'separator' },
        {
            label: '退出',
            click: () => {
                log.info('User requested quit from tray');
                app.isQuitting = true;
                app.quit();
            }
        }
    ]);

    tray.setToolTip('Vantage');
    tray.setContextMenu(contextMenu);

    tray.on('double-click', () => {
        mainWindow.show();
        mainWindow.focus();
        log.info('Window restored via tray double-click');
    });
}

// 单例模式
const gotTheLock = app.requestSingleInstanceLock();

if (!gotTheLock) {
    log.warn('Another instance is already running. Quitting this instance.');
    app.quit();
} else {
    app.on('second-instance', () => {
        log.info('Second instance detected, focusing existing window');
        if (mainWindow) {
            if (mainWindow.isMinimized()) mainWindow.restore();
            mainWindow.show();
            mainWindow.focus();
        }
    });

    app.whenReady().then(() => {
        log.info('App ready, initializing...');
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
});

const { app, BrowserWindow, Tray, Menu, nativeImage, dialog, ipcMain, Notification, safeStorage, powerMonitor } = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const { Runner } = require('./core/runner.cjs');
const { ProjectFiles, atomicWrite, readText } = require('./core/files.cjs');
const { Application } = require('./core/application.cjs');
const { ResourceStore, startResourceBroker } = require('./core/resources.cjs');
const { discoverProjects } = require('./core/discovery.cjs');
const { DailyNotifier } = require('./core/notifications.cjs');
const { BoundedOutput, sanitizeOutput } = require('./core/live-output.cjs');
const { createLoginStartup } = require('./core/login-startup.cjs');

app.setName('Never Stop');
app.setPath('userData', process.env.NEVER_STOP_DATA_DIR || path.join(app.getPath('appData'), 'VantageNeverStop'));
app.setAppUserModelId('com.vantage.never-stop');
let window, tray, runner, application, notifier, refreshTimer;
let quitting = false, initializing = true, broadcastPending = false;
let endingSession = false;
const brokers = new Map();
const notifications = new Set();
const dataDir = app.getPath('userData');
const loginStartup = createLoginStartup({ app, entryFile: __filename });

function showWindow(id) {
  if (!window || window.isDestroyed()) createWindow();
  window.show(); window.focus();
  if (id) window.webContents.send('never-stop:change', { selectedProjectId: id });
}
function createWindow() {
  window = new BrowserWindow({ width: 1280, height: 860, minWidth: 900, minHeight: 640,
    title: 'Never Stop', backgroundColor: '#10131a', show: false,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  window.removeMenu();
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', event => event.preventDefault());
  window.on('close', event => { if (!quitting) { event.preventDefault(); window.hide(); } });
  window.on('query-session-end', () => { endingSession = true; });
  window.on('session-end', () => { endingSession = true; void runner?.shutdown({ preserveIntent: true }); });
  window.loadFile(path.join(__dirname, 'dist', 'index.html'));
  window.once('ready-to-show', () => { if (!process.argv.includes('--background')) window.show(); });
}
function broadcast() {
  if (broadcastPending) return;
  broadcastPending = true;
  setTimeout(() => {
    broadcastPending = false;
    if (window && !window.isDestroyed()) window.webContents.send('never-stop:change', {});
  }, 100);
}
async function quit({ preserveIntent = endingSession } = {}) {
  if (quitting) return;
  quitting = true;
  clearInterval(refreshTimer); notifier?.stop();
  try {
    await runner?.shutdown({ preserveIntent });
    for (const broker of brokers.values()) await broker.close();
    tray?.destroy(); app.quit();
  } catch (error) { quitting = false; startTimers(); dialog.showErrorBox('无法结束受管理执行', error.message); }
}
async function pickDirectory(create) {
  if (create) {
    const result = await dialog.showSaveDialog(window, { title: '新建项目文件夹', buttonLabel: '新建文件夹', defaultPath: '新项目', properties: ['createDirectory', 'showOverwriteConfirmation'] });
    if (result.canceled) return null;
    await fs.mkdir(result.filePath, { recursive: true });
    return result.filePath;
  }
  const result = await dialog.showOpenDialog(window, { title: '选择项目根目录', properties: ['openDirectory', 'createDirectory'] });
  return result.canceled ? null : result.filePaths[0];
}
function testNotification() {
  if (!Notification.isSupported()) throw new Error('当前平台不支持原生通知，请检查系统设置');
  return new Promise((resolve, reject) => {
    const notification = new Notification({ title: 'Never Stop', body: '这是一条测试提醒。点击返回项目。' });
    notifications.add(notification);
    const timer = setTimeout(() => resolve({ status: 'requested', message: '已请求系统通知；请核对系统通知权限与通知中心。' }), 2000);
    notification.once('show', () => { clearTimeout(timer); resolve({ status: 'shown', message: '系统已确认显示通知。' }); });
    notification.once('failed', (_event, error) => { clearTimeout(timer); reject(new Error(`系统通知失败：${error}`)); notifications.delete(notification); });
    notification.on('click', () => showWindow());
    notification.on('close', () => notifications.delete(notification));
    notification.show();
  });
}
async function initialize() {
  await fs.mkdir(dataDir, { recursive: true });
  const principles = await fs.readFile(path.join(__dirname, 'never_stop_execution_principles_v0_1.md'), 'utf8');
  const resources = new ResourceStore({ dataDir, safeStorage }); await resources.init();
  const files = new ProjectFiles({ dataDir });
  const output = new BoundedOutput();
  runner = new Runner({ dataDir, principles, resourcesPrompt: project => resources.prompt(project.resourceIds),
    outputSecrets: project => (project.resourceIds || []).flatMap(id => {
      if (!resources.list().some(resource => resource.id === id)) return [];
      const resource = resources.credential(id);
      return [resource.password, resource.passphrase].filter(Boolean);
    }),
    executionEnv: async project => {
      if (!brokers.has(project.id)) brokers.set(project.id, await startResourceBroker(resources, { allowedIds: () => runner.snapshot().find(p => p.id === project.id)?.resourceIds || [] }));
      return brokers.get(project.id).env;
    },
  });
  const outputResourceIds = new Map();
  runner.on('change', projects => {
    outputResourceIds.clear();
    for (const project of projects) outputResourceIds.set(project.id, project.resourceIds || []);
  });
  runner.on('output', (id, entries) => {
    const resourceIds = outputResourceIds.get(id);
    if (!resourceIds) return;
    const secrets = [];
    try {
      for (const resourceId of resourceIds) {
        if (!resources.list().some(resource => resource.id === resourceId)) continue;
        const resource = resources.credential(resourceId);
        for (const value of [resource.password, resource.passphrase]) if (value) secrets.push(value);
      }
      output.append(id, entries.map(entry => ({ ...entry, text: sanitizeOutput(entry.text, secrets) })));
    } catch {
      output.append(id, [{ kind: 'error', text: '凭据脱敏暂不可用，本批运行输出已隐藏。' }]);
    }
  });
  application = new Application({ runner, files, dataDir, resources, principles, output, discover: discoverProjects, pickDirectory, testNotification,
    appVersion: app.isPackaged ? app.getVersion() : null,
    applySettings: settings => loginStartup.apply(settings),
    reconcileStartup: settings => loginStartup.reconcile(settings),
  });
  await application.init(); await runner.init();
  application.on('change', () => {
    const ids = new Set(runner.snapshot().map(project => project.id));
    for (const [id, broker] of brokers) if (!ids.has(id)) { brokers.delete(id); output.remove(id); void broker.close(); }
    broadcast();
  });
  ipcMain.handle('never-stop:invoke', async (event, method, payload) => {
    if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame) return { ok: false, error: '无效调用来源' };
    try { return { ok: true, value: await application.invoke(method, payload) }; }
    catch (error) { return { ok: false, error: String(error.message).slice(0, 2000) }; }
  });
  createWindow();
  const icon = nativeImage.createFromDataURL('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAIElEQVQ4T2NkYPj/n4ECwESJ5lEDRg0YNWDUgFEDBg0AAD1tAh/hQRYfAAAAAElFTkSuQmCC');
  tray = new Tray(icon); tray.setToolTip('Never Stop · 关闭窗口继续运行');
  tray.setContextMenu(Menu.buildFromTemplate([{ label: '打开 Never Stop', click: () => showWindow() }, { label: '关闭窗口后继续后台运行', enabled: false }, { type: 'separator' }, { label: '退出并暂停全部项目', click: () => quit() }]));
  tray.on('double-click', () => showWindow());
  const notificationState = path.join(dataDir, 'notifications.json');
  notifier = new DailyNotifier({ Notification, loadState: async () => JSON.parse(await readText(notificationState, '{}')),
    saveState: state => atomicWrite(notificationState, JSON.stringify(state)), onOpen: showWindow,
    onError: error => { application.settings.notificationError = error; broadcast(); },
  });
  application.files = files;
  startTimers();
  powerMonitor.on('shutdown', event => { event.preventDefault(); endingSession = true; void quit({ preserveIntent: true }); });
  initializing = false;
}
function startTimers() {
  if (!application || !notifier) return;
  clearInterval(refreshTimer);
  notifier.start(() => ({ enabled: application.settings.notificationsEnabled, time: application.settings.notificationTime }), () => runner.snapshot());
  let reading = false;
  refreshTimer = setInterval(async () => {
    if (reading || quitting) return; reading = true;
    try { await Promise.allSettled(runner.snapshot().map(project => application.files.readProgress(project.root))); broadcast(); }
    finally { reading = false; }
  }, 1500);
}

if (!app.requestSingleInstanceLock()) { quitting = true; app.quit(); }
else {
  app.on('second-instance', () => { if (!initializing) showWindow(); });
  app.on('window-all-closed', () => {});
  app.on('activate', () => { if (!initializing) showWindow(); });
  app.on('before-quit', event => { if (!quitting) { event.preventDefault(); void quit(); } });
  app.whenReady().then(initialize).catch(async error => {
    dialog.showErrorBox('Never Stop 启动失败', String(error.message));
    await quit();
  });
}

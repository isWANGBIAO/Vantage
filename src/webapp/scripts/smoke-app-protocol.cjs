// Synthetic local-only Electron smoke. No camera, model, or real user data is used.
const { app, BrowserWindow, protocol, session, ipcMain } = require('electron');
const { createServer } = require('node:http');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-protocol-smoke-'));
const assets = path.join(root, 'assets'); fs.mkdirSync(assets);
fs.mkdirSync(path.join(assets, 'assets'));
fs.writeFileSync(path.join(assets, 'index.html'), '<!doctype html><html><body>Protocol smoke<img id="asset" src="./assets/test.svg"><script src="./assets/test.js"></script></body></html>');
fs.writeFileSync(path.join(assets, 'assets', 'test.js'), 'window.protocolAssetLoaded = true;');
fs.writeFileSync(path.join(assets, 'assets', 'test.svg'), '<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"><rect width="2" height="2"/></svg>');
app.setPath('userData', path.join(root, 'user-data'));
if (process.platform === 'linux') {
    app.commandLine.appendSwitch('headless');
    app.commandLine.appendSwitch('ozone-platform', 'headless');
}

const { APP_SCHEME, APP_SCHEME_PRIVILEGES, installAppProtocol } = require('../src/utils/appProtocol.cjs');
protocol.registerSchemesAsPrivileged([{scheme: APP_SCHEME, privileges: APP_SCHEME_PRIVILEGES}]);
app.disableHardwareAcceleration();
app.on('window-all-closed', () => {});
let server;
app.whenReady().then(async () => {
    let streamClosed = false;
    let jobStatus = 'idle', cancelCount = 0; const calls = [];
    server = createServer(async (req, res) => {
        calls.push({ method: req.method, path: req.url, origin: req.headers.origin });
        if (req.url.endsWith('/cancel')) cancelCount++;
        if (req.method === 'POST') { for await (const _ of req) {} jobStatus = 'running'; setTimeout(() => { jobStatus = 'succeeded'; }, 400); res.setHeader('Content-Type', 'application/json'); res.end('{"id":"demo"}'); }
        else if (req.url.endsWith('/events')) {
            res.setHeader('Content-Type', 'application/x-ndjson'); res.write('{"step":"first"}\n');
            res.on('close', () => { streamClosed = true; });
        } else { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ status: jobStatus, cancelCount, streamClosed })); }
    });
    await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
    let window;
    ipcMain.on('platform:get-descriptor', event => {
        event.returnValue = event.sender === window?.webContents ? {
            kind: 'electron',
            backend: { baseUrl: `http://127.0.0.1:${server.address().port}`, rendererOrigin: 'vantage://app' },
        } : null;
    });
    ipcMain.handle('backend:wait-until-ready', async () => ({ ready: true }));
    installAppProtocol({ session: session.defaultSession, getWebContents: () => window?.webContents, assetRoot: assets, connection: { baseUrl: `http://127.0.0.1:${server.address().port}` } });
    window = new BrowserWindow({ show: false, webPreferences: { preload: path.join(__dirname, '..', 'preload.cjs'), offscreen: true, sandbox: true, contextIsolation: true, nodeIntegration: false } });
    await window.loadURL('vantage://app/index.html');
    const result = await window.webContents.executeJavaScript(`(async () => {
        const post = await fetch('/api/v1/action-plan/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({replace_today:true}) });
        const posted = await post.json();
        const controller = new AbortController();
        const start = performance.now();
        const stream = await fetch('/api/v1/action-plan/jobs/demo/events', { signal: controller.signal });
        const first = await stream.body.getReader().read();
        const elapsed = performance.now() - start;
        controller.abort();
        await new Promise(resolve => setTimeout(resolve, 500));
        const status = await (await fetch('/api/v1/action-plan/jobs/demo')).json();
        return { origin: location.origin, secure: isSecureContext, bridge: window.vantagePlatform.descriptor.backend.rendererOrigin, assetLoaded: window.protocolAssetLoaded && document.getElementById('asset').naturalWidth === 2, posted, first: new TextDecoder().decode(first.value), elapsed, status };
    })()`);
    const stranger = new BrowserWindow({ show: false, webPreferences: { offscreen: true, sandbox: true, contextIsolation: true, nodeIntegration: false } });
    await stranger.loadURL('data:text/html,<html><body>Untrusted</body></html>');
    const blocked = await stranger.webContents.executeJavaScript(`fetch('vantage://app/api/v1/action-plan/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(() => false, () => true)`);
    stranger.destroy();
    console.log('RESULT', JSON.stringify({ result, blocked, calls }));
    if (!result.secure || result.origin !== 'vantage://app' || result.posted.id !== 'demo' || !result.first.includes('first') || !result.assetLoaded || result.bridge !== 'vantage://app' || result.status.status !== 'succeeded' || result.status.cancelCount !== 0 || !result.status.streamClosed || !blocked || calls.length !== 3 || calls.some(call => call.method === 'OPTIONS')) throw new Error('Protocol smoke failed');
    window.webContents.stopPainting();
    window.destroy();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
    app.quit();
}).catch(error => { console.error(error); server?.closeAllConnections(); server?.close(); app.exit(1); });
setTimeout(() => { console.error('Protocol smoke timeout'); app.exit(1); }, 15000).unref();

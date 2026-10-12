// Run with Node. Crashes ONLY an isolated synthetic Electron child, never Vantage.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { createCrashDiagnostics } = require('../src/utils/crashDiagnostics.cjs');

if (process.versions.electron) {
    const { app, crashReporter, BrowserWindow } = require('electron');
    const root = process.env.VANTAGE_CRASH_SMOKE_ROOT;
    if (!root || path.dirname(root) !== os.tmpdir() || !path.basename(root).startsWith('vantage-crash-smoke-')) throw new Error('Isolated smoke root is required');
    app.setPath('userData', path.join(root, 'electron-user-data'));
    app.disableHardwareAcceleration();
    const diagnostics = createCrashDiagnostics({ dataDir: root });
    if (!diagnostics.startNativeCollector({ app, crashReporter }) || !diagnostics.startSession()) app.exit(2);
    fs.writeFileSync(path.join(root, 'collector-status.json'), JSON.stringify({ ...diagnostics.getStatus(), uploadToServer: crashReporter.getUploadToServer() }));
    app.whenReady().then(async () => {
        if (process.env.VANTAGE_CRASH_SMOKE_MODE !== 'renderer') {
            setTimeout(() => process.crash(), 500);
            return;
        }
        const window = new BrowserWindow({ show: false, webPreferences: { offscreen: true, sandbox: true, contextIsolation: true, nodeIntegration: false } });
        window.webContents.once('render-process-gone', (_event, details) => {
            diagnostics.recordExit('renderer', details);
            fs.writeFileSync(path.join(root, 'renderer-exit.json'), JSON.stringify({ reason: details.reason, exitCode: details.exitCode }));
            setTimeout(() => app.quit(), 1000);
        });
        app.on('before-quit', () => diagnostics.beginShutdown());
        app.on('quit', (_event, code) => { if (code === 0) diagnostics.markClean(); });
        await window.loadURL('data:text/html,<html><body>Synthetic crash smoke</body></html>');
        setTimeout(() => window.webContents.forcefullyCrashRenderer(), 500);
    });
} else {
    async function runCase(mode) {
        const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-crash-smoke-'));
        const electron = require('electron');
        const env = { ...process.env, VANTAGE_CRASH_SMOKE_ROOT: root, VANTAGE_CRASH_SMOKE_MODE: mode };
        delete env.ELECTRON_RUN_AS_NODE;
        const child = spawn(electron, [__filename, '--disable-gpu', '--headless', '--ozone-platform=headless'], { env, stdio: 'ignore', windowsHide: true });
        const exit = await new Promise((resolve, reject) => { child.once('error', reject); child.once('exit', (code, signal) => resolve({ code, signal })); });
        const status = JSON.parse(fs.readFileSync(path.join(root, 'collector-status.json'), 'utf8'));
        const dumps = [];
        function list(parent) {
            for (const entry of fs.readdirSync(parent, { withFileTypes: true })) {
                if (entry.isSymbolicLink()) continue;
                const target = path.join(parent, entry.name);
                if (entry.isDirectory()) list(target);
                else if (entry.name.endsWith('.dmp')) dumps.push(target);
            }
        }
        // Crashpad may finish persisting a dump shortly after the process exits.
        for (let attempt = 0; attempt < 40 && dumps.length === 0; attempt += 1) {
            list(path.join(root, 'diagnostics', 'electron'));
            if (!dumps.length) await new Promise(resolve => setTimeout(resolve, 250));
        }
        if (status.uploadToServer !== false || !status.nativeCollector || !dumps.length || (mode === 'main' && exit.code === 0)) throw new Error('Real local-only crash smoke failed');
        for (const filename of dumps) {
            const fd = fs.openSync(filename, 'r');
            const magic = Buffer.alloc(4); fs.readSync(fd, magic, 0, 4, 0); fs.closeSync(fd);
            if (magic.toString('ascii') !== 'MDMP') throw new Error('Invalid native minidump');
        }
        const recovered = createCrashDiagnostics({ dataDir: root });
        if (!recovered.startSession() || recovered.getStatus().previousInterrupted !== (mode === 'main')) throw new Error('Real crash did not recover expected session state');
        let rendererExit;
        if (mode === 'renderer') {
            rendererExit = JSON.parse(fs.readFileSync(path.join(root, 'renderer-exit.json'), 'utf8'));
            if (rendererExit.reason !== 'crashed' || exit.code !== 0) throw new Error('Renderer crash lifecycle failed');
            const incidentDirectory = path.join(root, 'diagnostics', 'incidents');
            const incidents = fs.readdirSync(incidentDirectory).map(name => JSON.parse(fs.readFileSync(path.join(incidentDirectory, name), 'utf8')));
            if (!incidents.some(incident => incident.processType === 'renderer' && incident.reason === 'crashed')) throw new Error('Renderer incident not recorded');
        }
        recovered.markClean();
        return { passed: true, mode, root, uploadToServer: false, dumpCount: dumps.length, dumpBytes: dumps.map(filename => fs.statSync(filename).size), exit, previousInterrupted: mode === 'main', rendererExit };
    }
    (async () => { console.log(JSON.stringify({ passed: true, cases: [await runCase('main'), await runCase('renderer')] })); })().catch(error => { console.error(error); process.exitCode = 1; });
}

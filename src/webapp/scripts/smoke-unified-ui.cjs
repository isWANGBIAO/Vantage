// Production React UI in an isolated Electron session. All data is synthetic;
// no Python backend, camera, provider, user configuration, or external network.
// Run `npm run build` first, then `npm run test:electron-ui`.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createServer } = require('node:http');
const { setTimeout: delay } = require('node:timers/promises');
const { app, BrowserWindow, ipcMain, protocol, session } = require('electron');
const { APP_SCHEME, APP_ENTRY_URL, APP_SCHEME_PRIVILEGES, installAppProtocol } = require('../src/utils/appProtocol.cjs');
const { resolveBackendConnection } = require('../src/utils/backendConnection.cjs');
const { createBackendJsonRequester } = require('../src/utils/backendTransport.cjs');

const assetRoot = path.join(__dirname, '..', 'dist');
assert.ok(fs.existsSync(path.join(assetRoot, 'index.html')), 'Build the production frontend before running this smoke test.');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-unified-ui-smoke-'));
app.setPath('userData', path.join(root, 'user-data'));
app.setPath('sessionData', path.join(root, 'session-data'));
app.setPath('crashDumps', path.join(root, 'crashes'));
app.disableHardwareAcceleration();
app.commandLine.appendSwitch('disable-background-networking');
if (process.platform === 'linux') {
    app.commandLine.appendSwitch('headless');
    app.commandLine.appendSwitch('ozone-platform', 'headless');
}
protocol.registerSchemesAsPrivileged([{ scheme: APP_SCHEME, privileges: APP_SCHEME_PRIVILEGES }]);
app.on('window-all-closed', () => {}); // Reopen the window during interruption tests.

const calls = [];
const errors = [];
const unexpectedRequests = [];
const forbiddenNetwork = [];
const pendingDiagnostics = new Set();
const expectedCancellations = [];
const activeRequests = new Set();
let lastNetworkActivity = 0;
const nativeCalls = { picker: 0, preferences: 0, themes: [] };
const settings = {
    display_language: 'en-US', theme: 'dark', theme_mode: 'dark',
    launch_at_login: false, action_plan_auto_generate: false,
    action_plan_check_interval_minutes: 0,
};
let onboardingCompleted = false;
let window;
let server;
let shuttingDown = false;
let backendConnection;
let smokeSession;

const chart = (id, title) => ({
    id, title, summary: [],
    option: {
        animation: false,
        xAxis: { type: 'category', data: ['Day 1', 'Day 2'] },
        yAxis: { type: 'value' },
        series: [{ name: 'Synthetic sample', type: 'line', data: [1, 2] }],
    },
});
const readFixtures = {
    '/api/v1/action-plan/today': {
        exists: true, date: '2026-01-01',
        analysis: { body: 'Synthetic smoke analysis' },
        plan: { body: 'Synthetic smoke action plan' },
    },
    '/api/v1/action-plan/jobs': { jobs: [], active: null },
    '/api/v1/chat/context': {
        base_context_version: 'smoke-empty', context_version: 'smoke-empty',
        has_action_plan_context: false, display_messages: [], messages: [], stats: null,
        preferred_model: null, preferred_provider_route: null, preferred_model_option_id: null,
    },
    '/api/v1/models': { models: [], providers: [], default_model: null },
    '/api/v1/projects/progress': {
        tasks: { pending: [{ project: 'Synthetic project', task: 'Verify the unified workspace' }], completed: [] },
        commits: [], stats: { completion_rate: 0, total_tasks: 1, completed_tasks: 0 },
    },
    '/api/v1/finance/balance-sheet': { sheets: [], summary: {}, source: {} },
    '/api/v1/finance/purchase-recommendations': { recommendation_groups: [], dismissed_count: 0 },
    '/api/v1/finance/purchase-recommendations/dismissed': { items: [], count: 0 },
    '/api/v1/plots/data': { charts: [chart('sleep-schedule', 'Synthetic sleep chart'), chart('balance', 'Synthetic balance chart')], warnings: [] },
    '/api/v1/system/logs': { logs: ['INFO Synthetic unified UI smoke is ready'] },
    '/api/v1/system/status': { camera_online: false, show_person_box: false, camera_frame_dark: false },
    '/api/v1/system/statistics': { cpu_usage: 12, memory_used_gb: 1, memory_percent: 25, disk_free_gb: 100 },
    '/api/v1/media/latest': { photo: null, screenshot: null },
    '/api/v1/system/air-quality': { aqi: null, city: 'Location unavailable', level: 'Unavailable', color: '#b2bec3', status: 'unavailable', lat: null, lon: null },
    '/api/v1/health/sedentary': { status: 'active', detection_status: 'unknown', is_sitting: false, duration_minutes: 0, duration_seconds: 0, away_duration_seconds: 0, active_timer: 'none', threshold_minutes: 60 },
    '/api/v1/face/report': { error: 'No report generated' },
    '/api/v1/face/live': { camera_online: false, points: [], window_seconds: 60 },
    '/api/v1/usage': { summary: {}, sources: [], sessions: [] },
};

function onboardingState() {
    return {
        completed: onboardingCompleted, displayLanguage: settings.display_language,
        launchAtLogin: false, providerConfigured: false, migrationCompleted: false, legacyRoot: null,
    };
}

function settingsState() {
    return { settings: { ...settings }, provider: { version: 2, selected_provider: null, providers: {} }, runtime_paths: {}, migration: {} };
}

async function serveFixture(req, res) {
    const pathname = new URL(req.url, 'http://127.0.0.1').pathname;
    const body = [];
    for await (const chunk of req) body.push(chunk);
    const payload = body.length ? JSON.parse(Buffer.concat(body).toString()) : undefined;
    calls.push({ method: req.method, pathname, ...(payload ? { payload } : {}) });
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Cache-Control', 'no-store');
    let result;
    if (req.method === 'GET' && pathname === '/api/v1/settings') result = settingsState();
    else if (req.method === 'GET' && pathname === '/api/v1/settings/display-language') result = { display_language: settings.display_language };
    else if (req.method === 'GET' && pathname === '/api/v1/onboarding') result = onboardingState();
    else if (req.method === 'PUT' && pathname === '/api/v1/settings') {
        Object.assign(settings, payload);
        result = settingsState();
    } else if (req.method === 'PUT' && pathname === '/api/v1/settings/display-language') {
        settings.display_language = payload.display_language;
        result = { display_language: settings.display_language };
    } else if (req.method === 'POST' && pathname === '/api/v1/onboarding/complete') {
        assert.equal(payload.skip_chat_setup, true, 'Onboarding must explicitly skip the provider.');
        assert.equal(payload.import_legacy_data, false, 'The smoke must not import user data.');
        assert.equal(payload.launch_at_login, false);
        assert.equal(payload.api_key, '');
        assert.equal(payload.legacy_root, '');
        onboardingCompleted = true;
        result = {
            completed: true, launchAtLogin: false, providerConfigured: false,
            migration: { imported: false, completed: false, sourcePath: null },
            settings: { display_language: settings.display_language, theme: settings.theme, theme_mode: settings.theme_mode, launch_at_login: false },
            provider: { selected_provider: null, providers: [] },
        };
    } else if (req.method === 'GET' && Object.hasOwn(readFixtures, pathname)) result = readFixtures[pathname];
    else {
        unexpectedRequests.push(`${req.method} ${pathname}`);
        res.statusCode = 404;
        result = { error: 'No synthetic fixture for this request' };
    }
    res.end(JSON.stringify(result));
}

async function checkErrors() {
    await Promise.all([...pendingDiagnostics]);
    assert.deepEqual(errors, [], 'Renderer errors');
    assert.deepEqual(unexpectedRequests, [], 'Unexpected backend requests');
    assert.deepEqual(forbiddenNetwork, [], 'Unexpected non-local renderer requests');
}

async function evaluate(fn, ...args) {
    return window.webContents.executeJavaScript(`(${fn.toString()})(...${JSON.stringify(args)})`);
}

async function waitFor(label, fn, ...args) {
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
        await checkErrors();
        if (await evaluate(fn, ...args)) return;
        await delay(50);
    }
    const text = await evaluate(() => document.body.innerText.slice(0, 2500));
    throw new Error(`Timed out waiting for ${label}\n${text}`);
}

async function click(selector, text = null) {
    await waitFor(`click target ${selector} ${text || ''}`, (selector, text) => [...document.querySelectorAll(selector)]
        .some(node => node.getClientRects().length && !node.disabled && (text === null || node.textContent.trim() === text)), selector, text);
    await evaluate((selector, text) => {
        const node = [...document.querySelectorAll(selector)].find(node => node.getClientRects().length && !node.disabled
            && (text === null || node.textContent.trim() === text));
        if (!node) throw new Error('Click target disappeared');
        node.click();
    }, selector, text);
}

async function expectStep(number) {
    await waitFor(`onboarding step ${number}`, number => document.querySelector('.onboarding-step-card[aria-current="step"] .onboarding-step-index')?.textContent === String(number), number);
}

async function createWindow() {
    window = new BrowserWindow({
        show: false, width: 1440, height: 1000, enableLargerThanScreen: true,
        webPreferences: {
            session: smokeSession, preload: path.join(__dirname, '..', 'preload.cjs'),
            offscreen: true, backgroundThrottling: false,
            sandbox: true, contextIsolation: true, nodeIntegration: false,
        },
    });
    const contents = window.webContents;
    contents.on('console-message', details => {
        // JavaScript console errors are classified below with their original
        // exception objects. This event also catches resource/security errors.
        if (!shuttingDown && details.level === 'error' && !details.message.startsWith('Failed to load model list:')) {
            errors.push(`${details.message} (${details.sourceId}:${details.lineNumber})`);
        }
    });
    contents.on('preload-error', (_event, _preload, error) => errors.push(`Preload: ${error.message}`));
    contents.on('render-process-gone', (_event, details) => {
        if (!shuttingDown) errors.push(`Renderer exited: ${details.reason}`);
    });
    contents.on('did-fail-load', (_event, code, description, url) => {
        if (code !== -3) errors.push(`Load failed: ${description} ${url}`);
    });
    contents.setWindowOpenHandler(() => ({ action: 'deny' }));
    // Observe exceptions before the production bundle runs, including rejected
    // promises. No test hook or replacement bridge is injected into the UI.
    console.log('STAGE new isolated window');
    contents.debugger.attach('1.3');
    contents.debugger.on('message', (_event, method, params) => {
        if (!shuttingDown && method === 'Runtime.exceptionThrown') {
            errors.push(params.exceptionDetails.exception?.description || params.exceptionDetails.text);
        }
        if (method === 'Network.requestWillBeSent') {
            activeRequests.add(`${contents.id}:${params.requestId}`);
            lastNetworkActivity = Date.now();
        } else if (method === 'Network.loadingFinished' || method === 'Network.loadingFailed') {
            activeRequests.delete(`${contents.id}:${params.requestId}`);
            lastNetworkActivity = Date.now();
        }
        if (!shuttingDown && method === 'Runtime.consoleAPICalled' && params.type === 'error'
            && params.args[0]?.value === 'Failed to load model list:') {
            const diagnostic = (async () => {
                const exception = params.args[1];
                const result = exception?.objectId ? await contents.debugger.sendCommand('Runtime.callFunctionOn', {
                    objectId: exception.objectId,
                    functionDeclaration: 'function () { return { name: this.name, message: this.message }; }',
                    returnByValue: true,
                }) : null;
                if (result?.result.value?.name === 'AbortError') {
                    // Existing ActionPlan logs its cancelled model request when
                    // display-language hydration restarts the effect at launch.
                    expectedCancellations.push('ActionPlan model request AbortError');
                } else {
                    errors.push(`Failed to load model list: ${exception?.description || exception?.value || 'unknown error'}`);
                }
            })().catch(error => errors.push(`Console diagnostic failed: ${error.message}`));
            pendingDiagnostics.add(diagnostic);
            void diagnostic.finally(() => pendingDiagnostics.delete(diagnostic));
        }
    });
    const observeRuntime = Promise.all([contents.debugger.sendCommand('Runtime.enable'), contents.debugger.sendCommand('Network.enable')]);
    await window.loadURL(APP_ENTRY_URL);
    await observeRuntime;
    // Headless Ozone may expose a 1x1 physical display. Fix the renderer's
    // desktop viewport without depending on a window manager or user display.
    await contents.debugger.sendCommand('Emulation.setDeviceMetricsOverride', {
        width: 1440, height: 1000, screenWidth: 1440, screenHeight: 1000,
        deviceScaleFactor: 1, mobile: false,
    });
    console.log('STAGE production document loaded');
    assert.deepEqual(await evaluate(() => ({ width: innerWidth, height: innerHeight })), { width: 1440, height: 1000 }, 'The production UI must render at desktop size.');
}

async function closeWindow() {
    await waitForNetworkIdle();
    window.webContents.stopPainting();
    if (window.webContents.debugger.isAttached()) window.webContents.debugger.detach();
    await new Promise(resolve => {
        window.once('closed', resolve);
        window.close();
    });
    assert.equal(window.isDestroyed(), true, 'The interrupted window must really close.');
    window = null;
}

async function waitForNetworkIdle() {
    const deadline = Date.now() + 10000;
    while (Date.now() < deadline) {
        await checkErrors();
        if (!activeRequests.size && Date.now() - lastNetworkActivity >= 150) return;
        await delay(25);
    }
    throw new Error(`Requests did not settle: ${[...activeRequests].join(', ')}`);
}

async function navigate(hash, selector, text) {
    await click(`.app-nav a[href="#${hash}"]`);
    await waitFor(`${hash} active page`, (hash, selector, text) => {
        const node = document.querySelector(selector);
        return location.hash === `#${hash}`
            && document.querySelector(`.app-nav a[href="#${hash}"]`)?.getAttribute('aria-current') === 'page'
            && [...document.querySelectorAll('.app-nav [aria-current="page"]')].length === 1
            && node?.getClientRects().length > 0 && (!text || node.innerText.includes(text));
    }, hash, selector, text);
    await waitForNetworkIdle();
}

async function openSettings() {
    await click('.settings-entry-button');
    await waitFor('loaded settings', () => location.hash === '#settings'
        && document.querySelector('.settings-entry-button')?.dataset.active === 'true'
        && document.querySelector('.settings-save-button')?.disabled === false
        && document.querySelector('.settings-page')?.getClientRects().length > 0);
    await waitForNetworkIdle();
}

async function exerciseUi() {
    await createWindow();
    await expectStep(1);
    const security = await evaluate(() => ({
        origin: location.origin, secure: isSecureContext,
        bridge: window.vantagePlatform?.descriptor.kind,
        rendererOrigin: window.vantagePlatform?.descriptor.backend.rendererOrigin,
        node: typeof window.require, process: typeof window.process, oldBridge: typeof window.electronAPI,
        scripts: [...document.scripts].map(script => script.src),
    }));
    assert.equal(security.origin, 'vantage://app');
    assert.equal(security.secure, true);
    assert.equal(security.bridge, 'electron');
    assert.equal(security.rendererOrigin, 'vantage://app');
    assert.equal(security.node, 'undefined');
    assert.equal(security.process, 'undefined');
    assert.equal(security.oldBridge, 'undefined');
    assert.ok(security.scripts.some(url => /^vantage:\/\/app\/assets\/.+\.js$/.test(url)), 'Real production Vite assets must load.');

    // Interrupted onboarding must not mark setup complete or leave stale steps.
    await click('.onboarding-actions button', 'Continue');
    await expectStep(2);
    await closeWindow();
    assert.equal(onboardingCompleted, false);
    await createWindow();
    await expectStep(1);
    await click('.onboarding-actions button', 'Continue');
    await expectStep(2);
    await click('.onboarding-actions button', 'Back');
    await expectStep(1);
    await click('.onboarding-actions button', 'Continue');
    await click('.onboarding-actions button', 'Skip Chat Setup');
    await expectStep(3);
    await click('.onboarding-inline-actions button', 'Choose Folder');
    await waitFor('cancelled folder picker', () => document.querySelector('.onboarding-inline-note')?.textContent.includes('No folder selected yet.')
        && document.querySelector('.onboarding-checkbox input')?.checked === false);
    assert.equal(nativeCalls.picker, 1);
    await click('.onboarding-actions button', 'Continue');
    await expectStep(4);
    await click('.onboarding-actions button', 'Back');
    await expectStep(3);
    await click('.onboarding-actions button', 'Continue');
    await click('.onboarding-actions button', 'Finish Setup');
    await waitFor('ready unified workspace', () => document.querySelectorAll('.app-nav a').length === 7
        && document.querySelector('.app-main')?.innerText.includes('Synthetic smoke action plan')
        && !document.querySelector('.onboarding-shell'));
    assert.equal(calls.filter(call => call.pathname === '/api/v1/onboarding/complete').length, 1);
    assert.ok(nativeCalls.preferences >= 1, 'Saved onboarding preferences must reach the native bridge.');
    console.log('PASS onboarding interruption, Back, cancelled picker, skip, and finish');

    await navigate('dashboard', '.dashboard-page', 'System Dashboard');
    await waitFor('synthetic dashboard data', () => document.querySelector('.dashboard-page')?.innerText.includes('12%'));
    if (process.env.VANTAGE_UI_SMOKE_SCREENSHOT) {
        await delay(200);
        const screenshot = await window.webContents.debugger.sendCommand('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
        fs.writeFileSync(process.env.VANTAGE_UI_SMOKE_SCREENSHOT, Buffer.from(screenshot.data, 'base64'));
    }
    await navigate('project-progress', '.project-progress-container', 'Verify the unified workspace');
    await navigate('expense-sheet', '.expense-sheet', 'Expense Sheet');
    await navigate('plots', '.app-main', 'Synthetic sleep chart');
    await waitFor('production chart rendering', () => [...document.querySelectorAll('.app-main canvas')].some(canvas => canvas.getClientRects().length && canvas.width > 0));
    await navigate('system-logs', '.app-main', 'Synthetic unified UI smoke is ready');
    await navigate('face-history', '.app-main', 'Face Dark Circles History');
    await navigate('action-plan', '.app-main', 'Synthetic smoke action plan');
    console.log('PASS all seven primary pages and synthetic data/chart rendering');

    // Settings is a page, not a dialog. Navigation is its close/cancel path:
    // unmounting without Save must discard edits, including after Back/Forward.
    await openSettings();
    await click('.settings-checkbox-row input');
    await waitFor('unsaved setting', () => document.querySelector('.settings-checkbox-row input')?.checked === true);
    await navigate('dashboard', '.dashboard-page', 'System Dashboard');
    await waitFor('settings dismissed', () => !document.querySelector('.settings-page'));
    await openSettings();
    await waitFor('unsaved setting discarded', () => document.querySelector('.settings-checkbox-row input')?.checked === false);
    assert.equal(calls.filter(call => call.method === 'PUT' && call.pathname === '/api/v1/settings').length, 0);
    await click('.settings-entry-button'); // Repeated entry is idempotent.
    assert.equal(await evaluate(() => document.querySelectorAll('.settings-page').length), 1);
    await navigate('dashboard', '.dashboard-page', 'System Dashboard');
    await evaluate(() => history.back());
    await waitFor('Back returns to settings', () => location.hash === '#settings' && document.querySelector('.settings-save-button')?.disabled === false);
    await evaluate(() => history.forward());
    await waitFor('Forward dismisses settings', () => location.hash === '#dashboard' && !document.querySelector('.settings-page'));
    await openSettings();
    for (const section of ['AI Provider', 'Voice Provider', 'Data & Logs', 'Performance', 'About', 'General']) {
        await click('.settings-sidebar button', section);
        await waitFor(`settings section ${section}`, section => document.querySelector('.settings-header h2')?.textContent === section, section);
    }
    await click('.settings-segmented button', 'Light');
    await click('.settings-save-button');
    await waitFor('saved light theme', () => document.documentElement.dataset.theme === 'light');
    assert.equal(settings.theme_mode, 'light');
    assert.equal(calls.filter(call => call.method === 'PUT' && call.pathname === '/api/v1/settings').length, 1);
    await navigate('action-plan', '.app-main', 'Synthetic smoke action plan');
    await closeWindow();
    await createWindow();
    await waitFor('completed setup stays complete on reopen', () => document.querySelectorAll('.app-nav a').length === 7
        && !document.querySelector('.onboarding-shell') && document.documentElement.dataset.theme === 'light');
    await openSettings();
    await waitFor('saved settings survive window reopen', () => document.querySelector('.settings-segmented .is-active')?.textContent === 'Light');
    await checkErrors();
    assert.ok(nativeCalls.themes.includes('light'));
    for (const pathname of Object.keys(readFixtures).filter(name => name !== '/api/v1/usage')) {
        assert.ok(calls.some(call => call.pathname === pathname), `UI did not request ${pathname}`);
    }
    assert.equal(calls.some(call => call.pathname.includes('/camera/stream')), false);
    console.log('PASS settings cancel/reopen, repeated entry, Back/Forward, sections, save/reopen');
    console.log('RESULT', JSON.stringify({ productionOrigin: security.origin, primaryPages: 7, rendererErrors: errors.length, expectedLifecycleCancellations: expectedCancellations.length, requests: calls.length, isolated: true }));
}

async function finish(code) {
    if (shuttingDown) return;
    shuttingDown = true;
    if (window && !window.isDestroyed()) {
        if (window.webContents.debugger.isAttached()) window.webContents.debugger.detach();
        window.destroy();
    }
    window = null;
    if (server) {
        server.closeAllConnections();
        await new Promise(resolve => server.close(resolve));
    }
    // Release storage files before removing the isolated temporary profile.
    await smokeSession?.clearStorageData();
    try {
        fs.rmSync(root, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
    } catch {
        // Windows may retain Chromium profile locks until process exit. It is
        // still a disposable OS-temp profile, never the real user's profile.
        console.warn('Temporary smoke profile cleanup deferred until OS temp cleanup.');
    }
    app.exit(code);
}

const timeout = setTimeout(() => {
    console.error('Unified UI smoke exceeded 90 seconds');
    void finish(1);
}, 90000);
timeout.unref();

app.whenReady().then(async () => {
    console.log('STAGE Electron ready');
    server = createServer((req, res) => {
        void serveFixture(req, res).catch(error => {
            errors.push(`Synthetic backend: ${error.message}`);
            res.writeHead(500).end('{}');
        });
    });
    await new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(0, '127.0.0.1', resolve);
    });
    backendConnection = resolveBackendConnection({ baseUrl: `http://127.0.0.1:${server.address().port}` });
    const requestBackendJson = createBackendJsonRequester({ connection: backendConnection });
    ipcMain.on('platform:get-descriptor', event => {
        event.returnValue = window && !window.isDestroyed() && event.sender === window.webContents ? {
            kind: 'electron', os: process.platform, systemLocale: 'en-US',
            capabilities: { customTitleBar: true, pickLegacyRoot: true, launchAtLogin: true, cameraAccess: false, openSettingsPath: false, notifications: false },
            backend: { ...backendConnection, rendererOrigin: 'vantage://app' },
            app: { version: '0.0.0-smoke', mode: 'electron' },
        } : null;
    });
    const handle = (channel, callback) => ipcMain.handle(channel, (event, ...args) => {
        if (shuttingDown) return null;
        assert.ok(window && !window.isDestroyed() && event.sender === window.webContents, 'Only the current app window may use the preload bridge.');
        return callback(...args);
    });
    handle('backend:wait-until-ready', () => ({ ready: true }));
    handle('backend:configuration-request', requestBackendJson);
    handle('platform:get-system-locale', () => 'en-US');
    handle('platform:apply-saved-preferences', () => { nativeCalls.preferences++; return { applied: true }; });
    handle('platform:set-title-bar-theme', theme => { nativeCalls.themes.push(theme); return { applied: true }; });
    handle('platform:pick-legacy-root', () => { nativeCalls.picker++; return { path: null }; });
    smokeSession = session.fromPartition('vantage-unified-ui-smoke');
    smokeSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    smokeSession.setPermissionCheckHandler(() => false);
    installAppProtocol({ session: smokeSession, getWebContents: () => window?.webContents, assetRoot, connection: backendConnection });
    // Preserve installAppProtocol's onBeforeRequest identity gate. This separate
    // stage denies direct network access; protocol proxying uses Node loopback.
    smokeSession.webRequest.onBeforeSendHeaders({ urls: ['http://*/*', 'https://*/*', 'ws://*/*', 'wss://*/*'] }, (details, callback) => {
        forbiddenNetwork.push(details.url);
        callback({ cancel: true });
    });
    await exerciseUi();
    await finish(0);
}).catch(async error => {
    console.error(error);
    console.error('DIAGNOSTICS', JSON.stringify({ errors, unexpectedRequests, forbiddenNetwork }));
    await finish(1);
});

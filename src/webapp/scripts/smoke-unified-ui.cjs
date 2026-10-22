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
let previousInterrupted = true;
let diagnosticsOpenFails = true;
let diagnosticsOpenCalls = 0;
let diagnosticsAvailable = true;
const settings = {
    display_language: 'en-US', theme: 'dark', theme_mode: 'dark',
    launch_at_login: false, action_plan_auto_generate: false,
    action_plan_check_interval_minutes: 0,
};
let onboardingCompleted = false;
const recoveryCase = process.env.VANTAGE_UI_RECOVERY_CASE || 'all';
const runsRecoveryCase = name => recoveryCase === 'all' || recoveryCase === name;
let expectedOnboardingSkip = true;
let window;
let server;
let shuttingDown = false;
let backendConnection;
let smokeSession;
let todayReadFailures = 0;
let todayReadFailuresObserved = 0;
const cameraResponses = [];
let cameraAttempts = 0;
let faceProgress = { status: 'queued', percent: 0 };
let faceProgressReads = 0;
let faceProgressDrops = 0;
let faceProgressDropsObserved = 0;
// A 4x4 solid-color synthetic JPEG, generated solely for transport tests.
const cameraJpeg = Buffer.from('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAEAAQDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDlqKKK9s8M/9k=', 'base64');

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
    '/api/v1/face/local-status': { ready: false, method: 'onnx', message: 'Synthetic local environment is not configured' },
    '/api/v1/body-analysis/status': { status: 'disabled', last_report_available: false },
    '/api/v1/usage': { summary: {}, sources: [], sessions: [] },
};
const fixtureStatus = {};
if (runsRecoveryCase('aqi')) {
    readFixtures['/api/v1/system/air-quality'] = { aqi: 62, city: 'Synthetic city', level: 'Moderate', color: '#aaa', status: 'ready' };
}
if (runsRecoveryCase('purchase-restore')) {
    readFixtures['/api/v1/finance/purchase-recommendations'] = {
        status: 'ready', cache_key: 'synthetic-cache', dismissed_count: 0,
        recommendation_groups: [{ key: 'practical', title: 'Synthetic practical', items: [{ name: 'Synthetic desk lamp', reason: 'Synthetic recommendation' }] }],
    };
}
if (runsRecoveryCase('finance-unavailable')) {
    readFixtures['/api/v1/finance/balance-sheet'] = {
        status: 'unavailable', source: { available: false, path: '/synthetic/private/Balance Sheet.xlsx' },
        error: 'File not found: /synthetic/private/Balance Sheet.xlsx',
    };
    readFixtures['/api/v1/plots/data'].charts[1] = { id: 'balance', title: 'Synthetic balance chart', empty: true, error: 'Synthetic balance validation failed', summary: [] };
}

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
    if (req.method === 'GET' && pathname === '/api/v1/camera/stream' && runsRecoveryCase('camera-preview')) {
        cameraAttempts++;
        res.writeHead(200, { 'Content-Type': 'multipart/x-mixed-replace; boundary=frame', 'Cache-Control': 'no-store' });
        res.flushHeaders();
        cameraResponses.push(res);
        if (cameraAttempts <= 2) res.socket.destroy();
        return; // Intentionally controlled TCP multipart stream, not a mocked DOM event.
    }
    if (req.method === 'GET' && pathname === '/api/v1/face/progress' && runsRecoveryCase('face-progress')) {
        faceProgressReads++;
        if (faceProgressDrops > 0) {
            faceProgressDrops--;
            faceProgressDropsObserved++;
            req.socket.destroy();
        } else res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(faceProgress));
        return;
    }
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Cache-Control', 'no-store');
    if (req.method === 'GET' && pathname === '/api/v1/action-plan/today' && todayReadFailures > 0) {
        todayReadFailures--;
        todayReadFailuresObserved++;
        res.end('{'); // A transient, fully consumed invalid backend response.
        return;
    }
    if (req.method === 'GET' && pathname === '/api/v1/action-plan/jobs/synthetic-recovery/events') {
        res.setHeader('Content-Type', 'application/x-ndjson');
        res.end(`${JSON.stringify({ sequence: 1, log: 'STREAM_ANALYSIS_CONTENT:"Synthetic incomplete progress"' })}\n`);
        return;
    }
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
        assert.equal(payload.skip_chat_setup, expectedOnboardingSkip, 'Onboarding must submit the current provider setup choice.');
        assert.equal(payload.import_legacy_data, false, 'The smoke must not import user data.');
        assert.equal(payload.launch_at_login, false);
        assert.equal(payload.api_key, expectedOnboardingSkip ? '' : 'synthetic-provider-key');
        assert.equal(payload.legacy_root, '');
        onboardingCompleted = true;
        result = {
            completed: true, launchAtLogin: false, providerConfigured: false,
            migration: { imported: false, completed: false, sourcePath: null },
            settings: { display_language: settings.display_language, theme: settings.theme, theme_mode: settings.theme_mode, launch_at_login: false },
            provider: { selected_provider: null, providers: [] },
        };
    } else if (req.method === 'POST' && pathname === '/api/v1/face/analyze' && runsRecoveryCase('face-progress')) result = { status: 'started' };
    else if (req.method === 'POST' && pathname === '/api/v1/plots/refresh') result = { ok: true };
    else if (req.method === 'POST' && pathname === '/api/v1/finance/purchase-recommendations/dismiss') {
        const item = { ...payload.item, id: 1, group_key: payload.group_key, cache_key: payload.cache_key };
        readFixtures['/api/v1/finance/purchase-recommendations/dismissed'] = { items: [item], count: 1 };
        result = { ok: true, item, count: 1 };
    } else if (req.method === 'DELETE' && pathname === '/api/v1/finance/purchase-recommendations/dismissed/1') {
        readFixtures['/api/v1/finance/purchase-recommendations/dismissed'] = { items: [], count: 0 };
        result = { ok: true, count: 0 };
    } else if (req.method === 'GET' && Object.hasOwn(readFixtures, pathname)) {
        res.statusCode = fixtureStatus[pathname] || 200;
        result = readFixtures[pathname];
    }
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

async function waitForFixture(label, predicate) {
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
        await checkErrors();
        if (predicate()) return;
        await delay(25);
    }
    throw new Error(`Timed out waiting for synthetic backend: ${label}`);
}

function sendCameraFrame(response) {
    assert.ok(response && !response.destroyed, 'A current multipart transport must be open');
    const write = () => {
        if (response.destroyed) return;
        response.write(`--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${cameraJpeg.length}\r\n\r\n`);
        response.write(cameraJpeg);
        response.write('\r\n');
    };
    write();
    const timer = setInterval(write, 100);
    response.once('close', () => clearInterval(timer));
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
    const imageState = await evaluate(() => [...document.querySelectorAll('img')].map(image => ({ src: image.src, width: image.naturalWidth, complete: image.complete })));
    throw new Error(`Timed out waiting for ${label}\n${text}\nImages: ${JSON.stringify(imageState)}; camera attempts: ${cameraAttempts}`);
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
        const expectedCameraFailure = runsRecoveryCase('camera-preview') && details.sourceId.includes('/api/v1/camera/stream')
            && details.message.startsWith('Failed to load resource:');
        if (!shuttingDown && details.level === 'error' && !details.message.startsWith('Failed to load model list:') && !expectedCameraFailure) {
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
    if (runsRecoveryCase('onboarding-back')) {
        await click('.onboarding-actions button', 'Back');
        await expectStep(2);
        assert.equal(await evaluate(() => [...document.querySelectorAll('.onboarding-input')].some(node => node.disabled)), false,
            'Returning to provider setup after Skip must re-enable its controls.');
        await evaluate(() => {
            for (const [index, value] of [[1, 'https://synthetic.invalid/v1'], [2, 'synthetic-provider-key'], [3, 'synthetic-model']]) {
                const input = document.querySelectorAll('.onboarding-input')[index];
                Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value);
                input.dispatchEvent(new Event('input', { bubbles: true }));
            }
        });
        await click('.onboarding-actions button', 'Skip Chat Setup');
        await expectStep(3);
        await click('.onboarding-actions button', 'Back');
        await expectStep(2);
        assert.deepEqual(await evaluate(() => [...document.querySelectorAll('.onboarding-input')].slice(1).map(node => node.value)),
            ['https://synthetic.invalid/v1', 'synthetic-provider-key', 'synthetic-model']);
        await click('.onboarding-actions button', 'Continue');
        await expectStep(3);
        expectedOnboardingSkip = false;
        console.log('PASS skipped provider setup can be resumed without losing fields (#51)');
    }
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
    await waitFor('ready unified workspace', () => document.querySelectorAll('.app-nav a').length === 8
        && document.querySelector('.app-main')?.innerText.includes('Synthetic smoke action plan')
        && !document.querySelector('.onboarding-shell'));
    assert.equal(calls.filter(call => call.pathname === '/api/v1/onboarding/complete').length, 1);
    assert.ok(nativeCalls.preferences >= 1, 'Saved onboarding preferences must reach the native bridge.');
    console.log('PASS onboarding interruption, Back, cancelled picker, skip, and finish');

    if (runsRecoveryCase('missing-job')) {
        const job = { id: 'synthetic-recovery', status: 'running', trigger: 'manual', event_cursor: 1 };
        readFixtures['/api/v1/action-plan/jobs/synthetic-recovery'] = job;
        readFixtures['/api/v1/action-plan/jobs'] = { jobs: [job], active: job };
        await waitFor('running job replaces saved view', () => document.querySelector('.app-main')?.innerText.includes('Synthetic incomplete progress'));
        todayReadFailures = 1;
        readFixtures['/api/v1/action-plan/jobs'] = { jobs: [], active: null };
        await waitFor('missing job reports transient saved-view failure', () => document.querySelector('.app-main')?.innerText.includes('Reconnecting to backend status'));
        await waitFor('next healthy poll recovers complete saved plan', () => document.querySelector('.app-main')?.innerText.includes('Synthetic smoke action plan')
            && !document.querySelector('.app-main')?.innerText.includes('Synthetic incomplete progress')
            && !document.querySelector('.app-main')?.innerText.includes('partial output is incomplete')
            && !document.querySelector('.app-main')?.innerText.includes('Reconnecting to backend status'));
        assert.equal(await evaluate(() => [...document.querySelectorAll('.action-plan-copy-button')]
            .filter(button => button.textContent.trim() === 'Copy Reply' && !button.disabled).length), 2,
            'Both restored complete replies must become available for copying.');
        assert.equal(todayReadFailuresObserved, 1);
        assert.equal(calls.some(call => call.method === 'POST' && call.pathname.startsWith('/api/v1/action-plan/jobs')), false,
            'Recovery observes existing work and must not generate or cancel.');
        console.log('PASS missing active job retries a failed saved-plan read (#133)');
    }

    if (runsRecoveryCase('empty-hash')) {
        await navigate('dashboard', '.dashboard-page', 'System Dashboard');
        await evaluate(() => history.back());
        await waitFor('Back restores initial empty-hash page', () => location.hash === ''
            && document.querySelector('.app-nav a[href="#action-plan"]')?.getAttribute('aria-current') === 'page'
            && document.querySelector('.app-main')?.innerText.includes('Synthetic smoke action plan'));
        await evaluate(() => history.forward());
        await waitFor('Forward restores dashboard', () => location.hash === '#dashboard'
            && document.querySelector('.app-nav a[href="#dashboard"]')?.getAttribute('aria-current') === 'page');
        console.log('PASS Back/Forward restores the initial no-hash page (#52)');
    }

    await navigate('dashboard', '.dashboard-page', 'System Dashboard');
    await waitFor('synthetic dashboard data', () => document.querySelector('.dashboard-page')?.innerText.includes('12%'));
    if (runsRecoveryCase('aqi')) {
        await waitFor('initial valid AQI', () => document.querySelector('.dashboard-page')?.innerText.includes('Synthetic city - Moderate'));
        fixtureStatus['/api/v1/system/air-quality'] = 503;
        await click('.app-nav a[href="#action-plan"]');
        await click('.app-nav a[href="#dashboard"]');
        await waitFor('AQI failure invalidates old current value', () => !document.querySelector('.dashboard-page')?.innerText.includes('Synthetic city - Moderate')
            && document.querySelector('.dashboard-page')?.innerText.includes('Measurement unavailable'));
        fixtureStatus['/api/v1/system/air-quality'] = 200;
        readFixtures['/api/v1/system/air-quality'] = { aqi: 84, city: 'Recovered city', level: 'Moderate', status: 'ready' };
        await navigate('action-plan', '.app-main', 'Synthetic smoke action plan');
        await navigate('dashboard', '.dashboard-page', 'System Dashboard');
        await waitFor('AQI automatically recovers', () => document.querySelector('.dashboard-page')?.innerText.includes('Recovered city - Moderate'));
        console.log('PASS failed AQI is unavailable, then recovers (#85)');
    }
    if (process.env.VANTAGE_UI_SMOKE_SCREENSHOT) {
        await delay(200);
        const screenshot = await window.webContents.debugger.sendCommand('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
        fs.writeFileSync(process.env.VANTAGE_UI_SMOKE_SCREENSHOT, Buffer.from(screenshot.data, 'base64'));
    }
    if (runsRecoveryCase('camera-preview')) {
        readFixtures['/api/v1/system/status'].camera_online = true;
        await navigate('action-plan', '.app-main', 'Synthetic smoke action plan');
        await navigate('dashboard', '.dashboard-page', 'System Dashboard');
        await waitFor('camera device ready but preview hidden', () => document.querySelector('.dashboard-page')?.innerText.includes('Camera hidden for privacy'));
        await click('.dashboard-media-privacy', 'Show media');
        await waitForFixture('first broken TCP camera transport', () => cameraAttempts >= 1);
        assert.equal(await evaluate(() => [...document.querySelectorAll('.dashboard-page div')].some(node => node.textContent.trim() === 'Live')), false,
            'A failed or undecoded transport must not claim Live.');
        await waitForFixture('automatic camera transport retry', () => cameraAttempts >= 3);
        await delay(100); // Let cancelled initial image requests retire before delivering pixels.
        sendCameraFrame(cameraResponses.at(-1));
        await waitFor('decoded multipart image becomes Live', () => document.querySelector('img[alt="Live camera stream"]')?.naturalWidth === 4
            && [...document.querySelectorAll('.dashboard-page div')].some(node => node.textContent.trim() === 'Live'));
        const liveAttempts = cameraAttempts;
        cameraResponses.at(-1).socket.destroy();
        await waitForFixture('live multipart TCP interruption reconnects', () => cameraAttempts > liveAttempts);
        await click('.dashboard-media-privacy', 'Hide media');
        const hiddenAttempts = cameraAttempts;
        await delay(1500);
        assert.equal(cameraAttempts, hiddenAttempts, 'Hidden media must stop automatic transport work.');
        await click('.dashboard-media-privacy', 'Show media');
        await waitForFixture('showing media starts a new transport session', () => cameraAttempts > hiddenAttempts);
        sendCameraFrame(cameraResponses.at(-1));
        await waitFor('reshown preview decodes before Live', () => document.querySelector('img[alt="Live camera stream"]')?.naturalWidth === 4
            && [...document.querySelectorAll('.dashboard-page div')].some(node => node.textContent.trim() === 'Live'));
        await click('.dashboard-media-privacy', 'Hide media');
        readFixtures['/api/v1/system/status'].camera_online = false;
        await waitForFixture('all hidden camera TCP responses are closed', () => cameraResponses.every(response => response.destroyed));
        console.log('PASS actual broken multipart TCP reconnects, hides, and resumes without false Live (#132)');
    }
    await navigate('project-progress', '.project-progress-container', 'Verify the unified workspace');
    await navigate('expense-sheet', '.expense-sheet', 'Expense Sheet');
    if (runsRecoveryCase('finance-unavailable')) {
        await waitFor('HTTP 200 finance unavailable is visible', () => document.querySelector('.expense-state-panel.expense-error-panel')?.textContent.includes('File not found: Balance Sheet.xlsx'));
        assert.equal(await evaluate(() => document.querySelector('.expense-state-panel.expense-error-panel')?.textContent.includes('/synthetic/private')), false,
            'The error notice must retain the reason without expanding the private source path.');
        readFixtures['/api/v1/finance/balance-sheet'] = { status: 'ready', sheets: [], summary: {}, source: { available: true } };
        await click('.expense-toolbar .expense-refresh-button');
        await waitFor('finance retry clears error', () => !document.querySelector('.expense-state-panel.expense-error-panel')
            && document.querySelector('.expense-sheet')?.innerText.includes('Synthetic balance validation failed'));
        console.log('PASS unavailable finance HTTP 200 is shown and retry recovers (#110)');
    }
    if (runsRecoveryCase('purchase-restore')) {
        await waitFor('synthetic purchase card', () => document.querySelector('.expense-purchase-item')?.textContent.includes('Synthetic desk lamp'));
        await click('.expense-purchase-item .expense-purchase-dismiss-button');
        await waitFor('purchase card dismissed', () => !document.querySelector('.expense-purchase-item'));
        await click('.expense-purchase-show-dismissed');
        await waitFor('dismissed card listed', () => document.querySelector('.expense-purchase-dismissed-item')?.textContent.includes('Synthetic desk lamp'));
        const generationCalls = calls.filter(call => call.pathname.endsWith('/regenerate')).length;
        await click('.expense-purchase-dismissed-item .expense-purchase-dismiss-button');
        await waitFor('single restored purchase card visible again', () => document.querySelector('.expense-purchase-item')?.textContent.includes('Synthetic desk lamp')
            && !document.querySelector('.expense-purchase-dismissed-item'));
        assert.equal(calls.filter(call => call.pathname.endsWith('/regenerate')).length, generationCalls, 'Restore must not invoke the model.');
        console.log('PASS restoring one dismissed purchase item returns its card without generation (#84)');
    }
    await navigate('plots', '.app-main', 'Synthetic sleep chart');
    await waitFor('production chart rendering', () => [...document.querySelectorAll('.app-main canvas')].some(canvas => canvas.getClientRects().length && canvas.width > 0));
    await navigate('system-logs', '.app-main', 'Synthetic unified UI smoke is ready');
    await navigate('body-analysis', '.app-main', 'Body Analysis');
    await waitFor('active dark-circles subpage', () => {
        const sections = document.querySelector('.app-main nav[aria-label="Body analysis sections"]');
        const selected = sections?.querySelector('button[aria-current="page"]');
        return selected?.textContent.trim() === 'Dark Circles'
            && sections.querySelectorAll('button[aria-current="page"]').length === 1
            && [...document.querySelectorAll('.app-main h2')].some(heading =>
                heading.getClientRects().length > 0 && heading.textContent.trim() === 'Face Dark Circles History');
    });
    await waitFor('dark-circles report response', () => [...document.querySelectorAll('.app-main strong')]
        .some(node => node.getClientRects().length > 0 && node.textContent.trim() === 'No analysis report yet.'));
    assert.ok(calls.some(call => call.method === 'GET' && call.pathname === '/api/v1/face/report'), 'The dark-circles subpage must load its report.');
    if (runsRecoveryCase('face-progress')) {
        await click('.app-main button', 'Analyze Now');
        await waitForFixture('queued face job progress', () => faceProgressReads >= 1);
        assert.equal(await evaluate(() => [...document.querySelectorAll('.app-main button')].find(button => button.textContent.trim() === 'Analyzing...')?.disabled), true);
        faceProgressDrops = 1;
        await waitForFixture('face progress connection interruption', () => faceProgressDropsObserved === 1);
        assert.equal(await evaluate(() => [...document.querySelectorAll('.app-main button')].find(button => button.textContent.trim() === 'Analyzing...')?.disabled), true,
            'A transport failure must not imply that a queued job has stopped.');
        faceProgress = { status: 'running', percent: 40 };
        const reads = faceProgressReads;
        await waitForFixture('healthy running face job progress', () => faceProgressReads > reads);
        assert.equal(await evaluate(() => [...document.querySelectorAll('.app-main button')].find(button => button.textContent.trim() === 'Analyzing...')?.disabled), true,
            'Authoritative running progress must remain active.');
        const reportReads = calls.filter(call => call.pathname === '/api/v1/face/report').length;
        readFixtures['/api/v1/face/report'] = { trend_views: {}, local_analysis: { method: 'onnx', algorithm_version: 'synthetic-recovered', latest_datetime: 'Synthetic recovered report' } };
        faceProgress = { status: 'idle', percent: 0 };
        await waitFor('idle after restart unlocks analysis with explanation', () => [...document.querySelectorAll('.app-main button')]
            .some(button => button.textContent.trim() === 'Analyze Now' && !button.disabled)
            && [...document.querySelectorAll('.app-main [role="status"]')].some(node => node.textContent.includes('no longer running'))
            && document.querySelector('.app-main')?.textContent.includes('Synthetic recovered report'));
        assert.ok(calls.filter(call => call.pathname === '/api/v1/face/report').length > reportReads);
        console.log('PASS queued/transport-failed/running face job stays active, idle unlocks and refreshes report (#134)');
    }
    await click('.app-nav a[href="#never-stop"]');
    await waitFor('Never Stop embedded page', () => location.hash === '#never-stop'
        && document.querySelector('.never-stop-page-host')?.shadowRoot?.querySelector('.brand')?.textContent.includes('Never Stop'));
    await navigate('action-plan', '.app-main', 'Synthetic smoke action plan');
    console.log('PASS all eight primary pages including embedded Never Stop');
    await waitFor('previous interrupted session notice', () => document.querySelector('.crash-diagnostics-notice')?.textContent.includes('previous session'));
    await click('.crash-diagnostics-notice button', 'Open crash records');
    await waitFor('safe diagnostics open failure', () => document.querySelector('.crash-diagnostics-notice')?.textContent.includes('Could not open'));
    diagnosticsOpenFails = false;
    await click('.crash-diagnostics-notice button', 'Open crash records');
    await waitFor('diagnostics error cleared', () => !document.querySelector('.crash-diagnostics-notice')?.textContent.includes('Could not open'));
    assert.equal(diagnosticsOpenCalls, 2);
    await click('.crash-diagnostics-notice button', 'Dismiss');
    await waitFor('notice dismissed without blocking workspace', () => !document.querySelector('.crash-diagnostics-notice') && document.querySelectorAll('.app-nav a').length === 8);
    previousInterrupted = false;

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
        if (section === 'About') {
            await waitFor('local diagnostics privacy explanation', () => document.querySelector('.settings-diagnostics')?.textContent.includes('never uploaded automatically'));
            await click('.settings-diagnostics button', 'Open crash records');
            assert.equal(diagnosticsOpenCalls, 3);
        }
    }
    await click('.settings-segmented button', 'Light');
    await click('.settings-save-button');
    await waitFor('saved light theme', () => document.documentElement.dataset.theme === 'light');
    assert.equal(settings.theme_mode, 'light');
    assert.equal(calls.filter(call => call.method === 'PUT' && call.pathname === '/api/v1/settings').length, 1);
    await navigate('action-plan', '.app-main', 'Synthetic smoke action plan');
    await closeWindow();
    await createWindow();
    await waitFor('completed setup stays complete on reopen', () => document.querySelectorAll('.app-nav a').length === 8
        && !document.querySelector('.onboarding-shell') && document.documentElement.dataset.theme === 'light');
    await waitFor('clean startup diagnostics status fetched', () => !document.querySelector('.crash-diagnostics-notice'));
    await openSettings();
    await waitFor('saved settings survive window reopen', () => document.querySelector('.settings-segmented .is-active')?.textContent === 'Light');
    await checkErrors();
    assert.ok(nativeCalls.themes.includes('light'));
    for (const pathname of Object.keys(readFixtures).filter(name => name !== '/api/v1/usage')) {
        assert.ok(calls.some(call => call.pathname === pathname), `UI did not request ${pathname}`);
    }
    assert.equal(calls.some(call => call.pathname.includes('/camera/stream')), runsRecoveryCase('camera-preview'));
    console.log('PASS settings cancel/reopen, repeated entry, Back/Forward, sections, save/reopen');
    console.log('PASS crash notice, local-only privacy copy, narrow folder action and clean startup');
    await evaluate(() => {
        const select = document.querySelector('.settings-section select');
        select.value = 'zh-CN';
        select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await click('.settings-save-button');
    await waitFor('Chinese display saved', () => document.querySelector('.settings-header h2')?.textContent === '通用');
    await click('.settings-sidebar button', '关于');
    await waitFor('Chinese local-only privacy copy', () => document.querySelector('.settings-diagnostics')?.textContent.includes('不会自动上传'));
    diagnosticsAvailable = false;
    await closeWindow();
    await createWindow();
    await waitFor('Chinese workspace reopened', () => document.querySelectorAll('.app-nav a').length === 8);
    await click('.settings-entry-button');
    await click('.settings-sidebar button', '关于');
    await waitFor('diagnostics storage failure is visible and cannot open', () => document.querySelector('.settings-diagnostics')?.textContent.includes('不可用') && document.querySelector('.settings-diagnostics button')?.disabled === true);
    await checkErrors();
    console.log('PASS Chinese privacy copy and unavailable diagnostics without blocking UI');
    console.log('RESULT', JSON.stringify({ productionOrigin: security.origin, primaryPages: 8, rendererErrors: errors.length, expectedLifecycleCancellations: expectedCancellations.length, requests: calls.length, isolated: true }));
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
    handle('diagnostics:get-status', () => ({ localOnly: true, available: diagnosticsAvailable, nativeCollector: diagnosticsAvailable, directory: 'synthetic-diagnostics', previousInterrupted }));
    handle('diagnostics:open-directory', () => { diagnosticsOpenCalls++; return { opened: !diagnosticsOpenFails }; });
    handle('never-stop:invoke', method => method === 'state'
        ? { ok: true, value: { appVersion: '0.0.0-smoke', projects: [], resources: [], settings: {}, principles: '' } }
        : { ok: false, error: 'Unsupported synthetic Never Stop operation' });
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

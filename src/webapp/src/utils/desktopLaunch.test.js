import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
let launcher;
try { launcher = require('./desktopLaunch.cjs'); } catch { launcher = {}; }

const APP = 'Z:\\Vantage\\Vantage.exe';
const BACKEND = 'Z:\\Vantage\\resources\\backend-runtime\\VantageBackend\\VantageBackend.exe';
const STAMP = '2026-10-31T01:00:00.000Z';
const INDEPENDENT = Object.freeze({ pid: 123, parentPid: 12, inJob: false,
    hasPackageIdentity: false, parentIsShell: true, isIndependent: true, createdAt: STAMP });
const reply = value => ({ status: 0, stdout: JSON.stringify(value) });
const options = extra => ({ platform: 'win32', isPackaged: true, appExecutable: APP,
    backendExecutable: BACKEND, pid: 123, argv: ['Vantage.exe'], env: {}, ...extra });

test('non-Windows and development startup are unchanged without probing', () => {
    for (const extra of [{ platform: 'linux' }, { platform: 'darwin' }, { isPackaged: false }]) {
        assert.deepEqual(launcher.prepareIndependentLaunch(options({ ...extra,
            spawnSyncProcess: () => assert.fail('must not launch') })), { action: 'continue' });
    }
});

test('continue requires verified native identity and returns only allowlisted metadata', () => {
    const calls = [];
    const result = launcher.prepareIndependentLaunch(options({ spawnSyncProcess: (...args) => {
        calls.push(args);
        return reply({ ...INDEPENDENT, secret: 'PRIVATE_SECRET', packageName: 'PRIVATE_PACKAGE' });
    } }));
    assert.deepEqual(result, { action: 'continue', identity: INDEPENDENT });
    assert.deepEqual(calls[0].slice(0, 2), [BACKEND, ['--diagnostics-isolation', '123']]);
    assert.doesNotMatch(JSON.stringify(result), /PRIVATE/);
});

test('unsafe startup relaunches only through the fixed backend desktop mode', () => {
    const calls = [];
    const independent = { ...INDEPENDENT, pid: 456 };
    const result = launcher.prepareIndependentLaunch(options({
        argv: ['Vantage.exe', '--url', 'PRIVATE_SECRET', '--arbitrary-mode'],
        spawnSyncProcess: (...args) => {
            calls.push(args);
            return calls.length === 1 ? reply({ ...INDEPENDENT, inJob: true, isIndependent: false })
                : reply({ pid: 456, isolation: 'desktop-independent', identity: independent });
        },
    }));
    assert.deepEqual(result, { action: 'relaunched', identity: independent });
    assert.deepEqual(calls[1].slice(0, 2), [BACKEND, ['--launch-desktop-app', APP]]);
    assert.doesNotMatch(JSON.stringify(calls), /PRIVATE_SECRET|arbitrary-mode|--url/);
});

test('independence is not inferred from a label, partial identity, or truthy strings', () => {
    const invalid = [
        { ...INDEPENDENT, inJob: true }, { ...INDEPENDENT, hasPackageIdentity: true },
        { ...INDEPENDENT, parentIsShell: false }, { ...INDEPENDENT, isIndependent: 'true' },
        { ...INDEPENDENT, parentPid: 0 }, { ...INDEPENDENT, pid: 999 },
        { ...INDEPENDENT, createdAt: 'invalid' }, { isIndependent: true },
    ];
    for (const identity of invalid) {
        const calls = [];
        const result = launcher.prepareIndependentLaunch(options({ spawnSyncProcess: (_exe, args) => {
            calls.push(args);
            return reply(args[0] === '--diagnostics-isolation' ? identity
                : { pid: 123, isolation: 'breakaway', identity: INDEPENDENT });
        } }));
        assert.equal(result.action, 'failed');
        assert.equal(calls.length, 2);
    }
});

test('relaunch acknowledgement must match actual new identity and safe isolation', () => {
    for (const response of [
        { pid: 456, isolation: 'desktop-independent', identity: { ...INDEPENDENT, pid: 999 } },
        { pid: 456, isolation: 'desktop-independent', identity: { ...INDEPENDENT, pid: 456, inJob: true } },
        { pid: 456, isolation: 'desktop-independent', identity: { ...INDEPENDENT, pid: 456, hasPackageIdentity: true } },
        { pid: 456, isolation: 'desktop-independent', identity: { ...INDEPENDENT, pid: 456, parentIsShell: false } },
        { pid: 123, isolation: 'desktop-independent', identity: INDEPENDENT },
        { pid: 456, isolation: 'desktop-independent' },
    ]) {
        assert.equal(launcher.prepareIndependentLaunch(options({ spawnSyncProcess: (_exe, args) =>
            reply(args[0] === '--diagnostics-isolation' ? { ...INDEPENDENT, inJob: true } : response),
        })).action, 'failed');
    }
});

test('a relaunched process cannot loop when its native identity is still unsafe', () => {
    let calls = 0;
    const result = launcher.prepareIndependentLaunch(options({
        argv: ['Vantage.exe', '--vantage-independent-start'],
        spawnSyncProcess: () => { calls += 1; return reply({ ...INDEPENDENT, parentIsShell: false }); },
    }));
    assert.deepEqual(result, { action: 'failed', reason: 'independence-not-verified' });
    assert.equal(calls, 1);
});

test('already-relaunched safe process continues without another relaunch', () => {
    let calls = 0;
    const result = launcher.prepareIndependentLaunch(options({
        argv: ['Vantage.exe', '--vantage-independent-start'],
        spawnSyncProcess: () => { calls += 1; return reply(INDEPENDENT); },
    }));
    assert.equal(result.action, 'continue');
    assert.equal(calls, 1);
});

test('helper failures never leak diagnostics text and cannot continue unsafe startup', () => {
    const failures = [
        () => { throw new Error('PRIVATE_SECRET'); },
        () => ({ status: null, signal: 'SIGTERM', error: new Error('PRIVATE_SECRET'), stdout: JSON.stringify(INDEPENDENT) }),
        () => ({ status: 0, error: new Error('PRIVATE_SECRET'), stdout: JSON.stringify(INDEPENDENT) }),
        () => ({ status: 3, stdout: JSON.stringify(INDEPENDENT), stderr: 'PRIVATE_SECRET' }),
        () => ({ status: 0, stdout: 'PRIVATE_SECRET' }),
        () => ({ status: 0, stdout: '[]' }),
    ];
    for (const spawnSyncProcess of failures) {
        const result = launcher.prepareIndependentLaunch(options({ spawnSyncProcess }));
        assert.equal(result.action, 'failed');
        assert.doesNotMatch(JSON.stringify(result), /PRIVATE_SECRET|Error|stack|stderr/);
    }
});

test('helper calls have bounded waits and no inherited credentials or Node override', () => {
    const env = { SystemRoot: 'Windows', Path: 'safe-bin', LOCALAPPDATA: 'profile',
        TEMP: 'temporary', API_KEY: 'PRIVATE_SECRET', ELECTRON_RUN_AS_NODE: '1',
        VANTAGE_BACKEND_URL: 'http://127.0.0.1:8001', VANTAGE_DATA_DIR: 'custom-profile',
    };
    let value;
    launcher.prepareIndependentLaunch(options({ env, spawnSyncProcess: (_exe, _args, settings) => {
        value = settings;
        return reply(INDEPENDENT);
    } }));
    assert.equal(value.windowsHide, true);
    assert.equal(value.encoding, 'utf8');
    assert.deepEqual(value.stdio, ['ignore', 'pipe', 'pipe']);
    assert.ok(value.timeout > 0 && value.timeout <= 10000);
    assert.ok(value.maxBuffer > 0 && value.maxBuffer <= 16384);
    assert.equal(value.env.SystemRoot, 'Windows');
    assert.equal(value.env.Path, 'safe-bin');
    assert.equal(value.env.API_KEY, undefined);
    assert.equal(value.env.ELECTRON_RUN_AS_NODE, undefined);
    assert.equal(value.env.VANTAGE_DATA_DIR, 'custom-profile');
    assert.equal(value.env.VANTAGE_BACKEND_URL, 'http://127.0.0.1:8001');
    assert.doesNotMatch(JSON.stringify(value), /PRIVATE_SECRET/);
    assert.equal(env.API_KEY, 'PRIVATE_SECRET');
});

test('main verifies independence before taking the singleton lock or writing a session', async () => {
    const { readFileSync } = await import('node:fs');
    const source = readFileSync(new URL('../../main.cjs', import.meta.url), 'utf8');
    const gate = source.indexOf('const desktopStartup = prepareIndependentLaunch(');
    assert.ok(gate > 0);
    assert.ok(gate < source.indexOf('app.requestSingleInstanceLock()'));
    assert.ok(gate < source.indexOf('crashDiagnostics = createCrashDiagnostics('));
    assert.match(source.slice(gate, source.indexOf('let buildInfo', gate)), /isPackaged: app\.isPackaged/);
    assert.match(source.slice(gate, source.indexOf('let buildInfo', gate)), /resolveBundledBackendExecutable\(\{ env: \{\} \}\)/);
    assert.match(source, /desktopStartup\.action === 'failed'/);
    assert.match(source, /desktopStartup\.action === 'relaunched'/);
    assert.match(source, /launchIdentity: desktopStartup\.identity/);
});

test('missing or unsafe executable configuration fails without starting a process', () => {
    for (const extra of [{ appExecutable: undefined }, { backendExecutable: '' },
        { appExecutable: 'relative.exe' }, { backendExecutable: 'Z:\\bad\u0000.exe' }]) {
        const result = launcher.prepareIndependentLaunch(options({ ...extra,
            spawnSyncProcess: () => assert.fail('invalid configuration must not spawn'),
        }));
        assert.deepEqual(result, { action: 'failed', reason: 'invalid-launch-configuration' });
    }
});

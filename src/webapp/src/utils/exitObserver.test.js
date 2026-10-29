import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
let observer;
try { observer = require('./exitObserver.cjs'); } catch { observer = {}; }

function fixture(t) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-observer-launch-'));
    t.after(() => fs.rmSync(root, { recursive: true, force: true }));
    const sessionId = 'd794ffdf-a5cb-49dd-848b-75676ff33319';
    fs.mkdirSync(path.join(root, 'diagnostics', 'sessions'), { recursive: true });
    fs.mkdirSync(path.join(root, 'diagnostics', 'lifecycle'));
    const statuses = [];
    const diagnostics = {
        getObserverSession: () => ({ sessionId, sessionPath: path.join(root, 'diagnostics', 'sessions', `${sessionId}.active.json`) }),
        setObserverStatus: status => statuses.push(status),
    };
    return { root, sessionId, diagnostics, statuses };
}

test('launcher waits for trusted ready acknowledgement and strips environment secrets', async t => {
    const f = fixture(t);
    let options;
    const result = await observer.startExitObserver({ diagnostics: f.diagnostics, dataDir: f.root,
        executablePath: 'synthetic-backend', platform: 'win32',
        env: { SystemRoot: 'Windows', PATH: 'bin', API_KEY: 'PRIVATE_SECRET' },
        spawnProcess: (_exe, args, value) => {
            options = value;
            assert.equal(args[0], '--diagnostics-launch');
            fs.writeFileSync(path.join(f.root, 'diagnostics', 'lifecycle', `watcher-${f.sessionId}.json`), JSON.stringify({
                schemaVersion: 1, sessionId: f.sessionId, status: 'ready', pid: 987, isolation: 'breakaway', secret: 'PRIVATE_SECRET',
            }));
            return new EventEmitter();
        } });
    assert.deepEqual(result, { status: 'ready', pid: 987, isolation: 'breakaway' });
    assert.equal(options.windowsHide, true);
    assert.equal(options.env.API_KEY, undefined);
    assert.doesNotMatch(JSON.stringify(f.statuses), /PRIVATE_SECRET/);
});

test('spawn errors and missing acknowledgement produce explicit failed status', async t => {
    const f = fixture(t);
    const result = await observer.startExitObserver({ diagnostics: f.diagnostics, dataDir: f.root,
        executablePath: 'synthetic-backend', platform: 'win32', timeoutMs: 20,
        spawnProcess: () => { throw new Error('PRIVATE_SECRET'); } });
    assert.equal(result.status, 'failed');
    assert.equal(f.statuses.at(-1).status, 'failed');
    assert.doesNotMatch(JSON.stringify(result), /PRIVATE_SECRET/);
    const noAck = await observer.startExitObserver({ diagnostics: f.diagnostics, dataDir: f.root,
        executablePath: 'synthetic-backend', platform: 'win32', timeoutMs: 20,
        spawnProcess: () => new EventEmitter() });
    assert.equal(noAck.status, 'failed');
});

test('wrong-session or linked acknowledgements cannot claim readiness', async t => {
    const f = fixture(t);
    const ack = path.join(f.root, 'diagnostics', 'lifecycle', `watcher-${f.sessionId}.json`);
    fs.writeFileSync(ack, JSON.stringify({ sessionId: 'other', status: 'ready', pid: 987 }));
    const result = await observer.startExitObserver({ diagnostics: f.diagnostics, dataDir: f.root,
        executablePath: 'synthetic-backend', platform: 'win32', timeoutMs: 20,
        spawnProcess: () => new EventEmitter() });
    assert.equal(result.status, 'failed');
});

test('unsupported systems explicitly retain recovery without pretending to observe', async t => {
    const f = fixture(t);
    const result = await observer.startExitObserver({ diagnostics: f.diagnostics, dataDir: f.root,
        platform: 'linux', spawnProcess: () => assert.fail('must not spawn') });
    assert.equal(result.status, 'unsupported');
});

test('observer loss is reported once and monitoring can stop cleanly', t => {
    const f = fixture(t);
    let tick;
    const warnings = [];
    const stop = observer.monitorExitObserver({ diagnostics: f.diagnostics,
        observer: { status: 'ready', pid: 987, isolation: 'breakaway' },
        schedule: callback => { tick = callback; return { unref() {} }; }, cancel: () => {},
        isAlive: () => false, onStopped: reason => warnings.push(reason) });
    tick(); tick(); stop();
    assert.deepEqual(warnings, ['observer-stopped']);
    assert.equal(f.statuses.at(-1).status, 'stopped');
});

test('a reused live observer PID with a stale or failed acknowledgement is not healthy', t => {
    const f = fixture(t);
    const ack = path.join(f.root, 'diagnostics', 'lifecycle', `watcher-${f.sessionId}.json`);
    fs.writeFileSync(ack, JSON.stringify({ schemaVersion: 1, sessionId: f.sessionId,
        status: 'ready', pid: 987, isolation: 'breakaway' }));
    const old = new Date(Date.now() - 60000); fs.utimesSync(ack, old, old);
    let tick;
    const warnings = [];
    const stop = observer.monitorExitObserver({ diagnostics: f.diagnostics, dataDir: f.root,
        observer: { status: 'ready', pid: 987, isolation: 'breakaway' },
        schedule: callback => { tick = callback; return { unref() {} }; }, cancel: () => {},
        isAlive: () => true, onStopped: reason => warnings.push(reason) });
    tick(); tick(); stop();
    assert.deepEqual(warnings, ['observer-stopped']);
});

test('previous-session native identity probe rejects a reused PID, not an unknown failure', () => {
    const prior = { pid: 987, startedAt: '2026-10-29T01:00:00.000Z' };
    assert.equal(observer.isSessionProcessAlive({ prior, executablePath: 'synthetic', platform: 'win32',
        spawnSyncProcess: () => ({ status: 0, stdout: JSON.stringify({ pid: 987, alive: false }) }) }), false);
    assert.equal(observer.isSessionProcessAlive({ prior, executablePath: 'synthetic', platform: 'win32',
        fallback: () => true, spawnSyncProcess: () => ({ status: 1, stdout: 'PRIVATE_SECRET' }) }), true);
});

test('main connects readiness, identity checks, failure warnings and shutdown cleanup', () => {
    const source = fs.readFileSync(new URL('../../main.cjs', import.meta.url), 'utf8');
    assert.match(source, /isSessionAlive: prior => isSessionProcessAlive/);
    assert.match(source, /if \(!crashDiagnostics\.getStatus\(\)\.available/);
    assert.match(source, /startExitObserver\(/);
    assert.match(source, /monitorExitObserver\(/);
    assert.match(source, /stopExitObserverHealth\(\)/);
    assert.match(source, /Exit observer unavailable/);
    assert.match(source, /Exit diagnostics degraded: reused or external backend is not owned by this session/);
});

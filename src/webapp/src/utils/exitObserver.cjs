const fs = require('node:fs');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const { verifiedIdentity } = require('./desktopLaunch.cjs');

function observerEnvironment(env, dataDir) {
    const allowed = new Set(['systemroot', 'windir', 'path', 'pathext', 'temp', 'tmp', 'localappdata', 'userprofile']);
    const result = Object.fromEntries(Object.entries(env).filter(([key]) => allowed.has(key.toLowerCase())));
    return { ...result, VANTAGE_APP_MODE: 'packaged', VANTAGE_DATA_DIR: dataDir };
}

function readAcknowledgement(filename, sessionId) {
    for (const directory of [path.dirname(path.dirname(filename)), path.dirname(filename)]) {
        const info = fs.lstatSync(directory);
        if (!info.isDirectory() || info.isSymbolicLink()) throw new Error('unsafe-acknowledgement');
    }
    const info = fs.lstatSync(filename);
    if (!info.isFile() || info.isSymbolicLink() || info.size > 4096) throw new Error('unsafe-acknowledgement');
    const value = JSON.parse(fs.readFileSync(filename, 'utf8'));
    if (value.schemaVersion !== 1 || value.sessionId !== sessionId || !['ready', 'failed'].includes(value.status)) throw new Error('invalid-acknowledgement');
    if (!Number.isSafeInteger(value.pid) || value.pid <= 0 || value.pid > 0xffffffff) throw new Error('invalid-observer-pid');
    if (value.status === 'failed') return { status: 'failed', pid: value.pid, isolation: 'unknown' };
    const identity = verifiedIdentity(value.identity, value.pid);
    if (value.isolation !== 'desktop-independent' || !identity) throw new Error('unverified-observer');
    return { status: 'ready', pid: value.pid, isolation: 'desktop-independent', identity };
}

async function startExitObserver({ diagnostics, dataDir, executablePath, env = process.env,
    platform = process.platform, spawnProcess = spawn, timeoutMs = 10000 } = {}) {
    const publish = value => { diagnostics.setObserverStatus(value); return value; };
    if (platform !== 'win32') return publish({ status: 'unsupported', isolation: 'unsupported', pid: null });
    const session = diagnostics.getObserverSession();
    const failed = () => publish({ status: 'failed', isolation: 'unknown', pid: null });
    if (!session || !executablePath) return failed();
    const directory = path.join(dataDir, 'diagnostics');
    if (session.sessionPath !== path.join(directory, 'sessions', `${session.sessionId}.active.json`)
        || !/^[0-9a-f-]{36}$/i.test(session.sessionId)) return failed();
    const ack = path.join(directory, 'lifecycle', `watcher-${session.sessionId}.json`);
    publish({ status: 'starting', isolation: 'unknown', pid: null });
    let child;
    let spawnFailed = false;
    const onError = () => { spawnFailed = true; };
    const onExit = code => { if (code !== 0) spawnFailed = true; };
    try {
        child = spawnProcess(executablePath, ['--diagnostics-launch', session.sessionPath], {
            env: observerEnvironment(env, dataDir), stdio: 'ignore', windowsHide: true,
        });
        child.once('error', onError);
        child.once('exit', onExit);
        child.unref?.();
        const deadline = Date.now() + timeoutMs;
        while (!spawnFailed && Date.now() < deadline) {
            try { return publish(readAcknowledgement(ack, session.sessionId)); }
            catch (error) { if (error.code !== 'ENOENT') return failed(); }
            await new Promise(resolve => setTimeout(resolve, 25));
        }
        return failed();
    } catch { return failed(); }
    finally {
        child?.removeListener('error', onError);
        // A late spawn error after acknowledgement timeout must not become an
        // unhandled EventEmitter error in the application's main process.
        child?.on('error', () => {});
        child?.removeListener('exit', onExit);
    }
}

function processIsAlive(pid) {
    try { process.kill(pid, 0); return true; }
    catch (error) { return error.code !== 'ESRCH'; }
}

function isSessionProcessAlive({ prior, executablePath, env = process.env, dataDir,
    platform = process.platform, spawnSyncProcess = spawnSync, fallback = processIsAlive,
    onFailure = () => {} } = {}) {
    if (platform !== 'win32' || !executablePath) return fallback(prior.pid);
    try {
        const result = spawnSyncProcess(executablePath,
            ['--diagnostics-probe', String(prior.pid), prior.startedAt], {
                env: observerEnvironment(env, dataDir), windowsHide: true,
                encoding: 'utf8', timeout: 5000, maxBuffer: 4096,
            });
        if (result.status === 0) {
            const value = JSON.parse(result.stdout);
            if (value.pid === prior.pid && typeof value.alive === 'boolean') return value.alive;
        }
    } catch { /* Unknown identity is not permission to overwrite a live session. */ }
    onFailure('identity-probe-failed');
    return fallback(prior.pid);
}

function monitorExitObserver({ diagnostics, observer, dataDir, onStopped = () => {},
    isAlive = processIsAlive, schedule = setInterval, cancel = clearInterval } = {}) {
    if (observer.status !== 'ready') return () => {};
    let stopped = false;
    let staleChecks = 0;
    const identity = diagnostics.getObserverSession();
    const ack = dataDir && identity ? path.join(dataDir, 'diagnostics', 'lifecycle', `watcher-${identity.sessionId}.json`) : null;
    const timer = schedule(() => {
        if (stopped) return;
        let healthy = isAlive(observer.pid);
        if (healthy && ack) {
            try {
                const state = readAcknowledgement(ack, identity.sessionId);
                const fresh = Date.now() - fs.statSync(ack).mtimeMs <= 15000;
                if (state.status === 'failed' || state.pid !== observer.pid
                    || state.identity?.createdAt !== observer.identity?.createdAt) healthy = false;
                else if (fresh) staleChecks = 0;
                else healthy = ++staleChecks < 2;
            } catch { healthy = ++staleChecks < 2; }
        }
        if (healthy) return;
        stopped = true;
        diagnostics.setObserverStatus({ ...observer, status: 'stopped' });
        onStopped('observer-stopped');
        cancel(timer);
    }, 5000);
    timer.unref?.();
    return () => { stopped = true; cancel(timer); };
}

module.exports = { startExitObserver, monitorExitObserver, isSessionProcessAlive, observerEnvironment };

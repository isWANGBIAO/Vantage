const path = require('node:path');
const { spawnSync } = require('node:child_process');

const RESTART_FLAG = '--vantage-independent-start';
const ENVIRONMENT_KEYS = new Set([
    'systemroot', 'windir', 'path', 'pathext', 'temp', 'tmp', 'localappdata', 'userprofile',
    'appdata', 'homedrive', 'homepath', 'username', 'userdomain',
    'vantage_data_dir', 'vantage_config_dir', 'vantage_history_dir', 'vantage_log_dir',
    'vantage_plot_dir', 'vantage_cache_dir', 'vantage_runtime_dir', 'vantage_migration_dir',
    'vantage_backend_url', 'vantage_backend_host', 'vantage_backend_port',
]);
const validPid = value => Number.isSafeInteger(value) && value > 0 && value <= 0xffffffff;
const validExecutable = value => typeof value === 'string' && value.length > 0
    && !value.includes('\0') && path.win32.isAbsolute(value);

function readHelperResult(result) {
    if (!result || result.status !== 0 || result.error != null || result.signal != null
        || typeof result.stdout !== 'string' || Buffer.byteLength(result.stdout, 'utf8') > 16384) return null;
    try {
        const value = JSON.parse(result.stdout);
        return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
    } catch { return null; }
}

function verifiedIdentity(value, expectedPid) {
    if (!value || typeof value !== 'object' || !validPid(expectedPid) || value.pid !== expectedPid
        || !validPid(value.parentPid) || value.inJob !== false || value.hasPackageIdentity !== false
        || value.parentIsShell !== true || value.isIndependent !== true
        || typeof value.createdAt !== 'string' || value.createdAt.length > 40
        || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,7})?(?:Z|[+-]\d{2}:\d{2})$/.test(value.createdAt)
        || !Number.isFinite(Date.parse(value.createdAt))) return null;
    return { pid: value.pid, parentPid: value.parentPid, inJob: false,
        hasPackageIdentity: false, parentIsShell: true, isIndependent: true, createdAt: value.createdAt };
}

function prepareIndependentLaunch({ platform = process.platform, isPackaged,
    appExecutable, backendExecutable, env = process.env, argv = process.argv,
    pid = process.pid, spawnSyncProcess = spawnSync } = {}) {
    if (platform !== 'win32' || !isPackaged) return { action: 'continue' };
    if (!validExecutable(appExecutable) || !validExecutable(backendExecutable) || !validPid(pid)) {
        return { action: 'failed', reason: 'invalid-launch-configuration' };
    }
    const environment = Object.fromEntries(Object.entries(env || {}).filter(([key, value]) =>
        ENVIRONMENT_KEYS.has(key.toLowerCase()) && typeof value === 'string'));
    const call = args => {
        try {
            return readHelperResult(spawnSyncProcess(backendExecutable, args, {
                env: environment, encoding: 'utf8', timeout: 10000,
                // A regular libuv spawn enrolls its *parent* in a private job.
                // The identity probe must not mutate the identity it inspects.
                detached: true, maxBuffer: 16384, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
            }));
        } catch { return null; }
    };
    const probe = call(['--diagnostics-isolation', String(pid)]);
    const identity = verifiedIdentity(probe, pid);
    if (identity) return { action: 'continue', identity };
    // This flag is only a loop guard. It is never accepted as proof of isolation.
    if (Array.isArray(argv) && argv.includes(RESTART_FLAG)) {
        return { action: 'failed', reason: 'independence-not-verified' };
    }
    // Never forward arbitrary arguments or launcher diagnostics to the new app.
    const launched = call(['--launch-desktop-app', appExecutable]);
    const launchedIdentity = launched?.isolation === 'desktop-independent'
        && launched.pid !== pid ? verifiedIdentity(launched.identity, launched.pid) : null;
    return launchedIdentity ? { action: 'relaunched', identity: launchedIdentity }
        : { action: 'failed', reason: 'independent-launch-failed' };
}

module.exports = { prepareIndependentLaunch, verifiedIdentity };

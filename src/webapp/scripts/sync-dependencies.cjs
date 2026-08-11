'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const { performance } = require('node:perf_hooks');

const STATE_FILE_NAME = '.vantage-package-lock-state.json';
const DEPENDENCY_SYNC_LOCK_FILE_NAME = '.vantage-frontend-dependency-sync.lock';
const DEFAULT_DEPENDENCY_SYNC_LOCK_TIMEOUT_MILLISECONDS = 300_000;
const DEPENDENCY_SYNC_LOCK_POLL_MILLISECONDS = 50;
const DEPENDENCY_SYNC_LOCK_INITIALIZATION_GRACE_MILLISECONDS = 2_000;
const DEPENDENCY_SYNC_LOCK_HELPER_START_TIMEOUT_MILLISECONDS = 5_000;
const DEPENDENCY_SYNC_LOCK_HELPER_ARGUMENT = '--dependency-sync-lock-helper';
const LOCK_SLEEP_ARRAY = new Int32Array(new SharedArrayBuffer(4));
const STATE_FIELDS = Object.freeze([
  'packageLockSha256',
  'nodeVersion',
  'nodeModulesAbi',
  'platform',
  'arch',
]);

function dependencySyncLockPath(webappRoot) {
  return path.join(
    path.resolve(webappRoot),
    DEPENDENCY_SYNC_LOCK_FILE_NAME,
  );
}

function sanitizedDependencyLockError(error) {
  if (
    error instanceof Error
    && (
      error.message.startsWith('Frontend dependency synchronization lock')
      || error.message === (
        'Timed out waiting for frontend dependency synchronization lock.'
      )
    )
  ) {
    return error;
  }
  const errorCode = typeof error?.code === 'string' ? ` (${error.code})` : '';
  return new Error(
    `Frontend dependency synchronization lock operation failed${errorCode}.`,
  );
}

function sleepSynchronously(milliseconds) {
  Atomics.wait(LOCK_SLEEP_ARRAY, 0, 0, milliseconds);
}

function sameFileIdentity(left, right) {
  return left.dev === right.dev
    && left.ino === right.ino
    && left.mode === right.mode;
}

function validateLockFileStats(stats) {
  if (!stats.isFile() || stats.isSymbolicLink()) {
    throw new Error('Frontend dependency synchronization lock is unsafe.');
  }
  if (stats.nlink !== 1) {
    throw new Error('Frontend dependency synchronization lock is unsafe.');
  }
}

function readLockSnapshot(lockPath) {
  let initialStats;
  try {
    initialStats = fs.lstatSync(lockPath);
  } catch (error) {
    if (error.code === 'ENOENT') {
      return { kind: 'missing' };
    }
    throw error;
  }
  validateLockFileStats(initialStats);

  let descriptor;
  try {
    descriptor = fs.openSync(lockPath, 'r');
    const openedStats = fs.fstatSync(descriptor);
    validateLockFileStats(openedStats);
    if (!sameFileIdentity(initialStats, openedStats)) {
      throw new Error('Frontend dependency synchronization lock changed.');
    }
    const contents = fs.readFileSync(descriptor, 'utf8');
    const finalStats = fs.lstatSync(lockPath);
    validateLockFileStats(finalStats);
    if (!sameFileIdentity(openedStats, finalStats)) {
      throw new Error('Frontend dependency synchronization lock changed.');
    }

    let owner = null;
    try {
      const candidate = JSON.parse(contents);
      if (
        candidate.schemaVersion === 1
        && Number.isSafeInteger(candidate.pid)
        && candidate.pid > 0
        && typeof candidate.token === 'string'
        && candidate.token.length > 0
        && candidate.token.length <= 128
        && Number.isFinite(candidate.createdAtMilliseconds)
      ) {
        owner = candidate;
      }
    } catch {
      owner = null;
    }
    return {
      kind: owner === null ? 'initializing' : 'owned',
      owner,
      stats: finalStats,
    };
  } catch (error) {
    if (error.code === 'ENOENT') {
      return { kind: 'missing' };
    }
    throw error;
  } finally {
    if (descriptor !== undefined) {
      fs.closeSync(descriptor);
    }
  }
}

function processIsAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === 'EPERM';
  }
}

function quarantineStaleLock(lockPath, snapshot) {
  const quarantinePath = `${lockPath}.stale-${process.pid}-${crypto.randomBytes(8).toString('hex')}`;
  try {
    fs.renameSync(lockPath, quarantinePath);
  } catch (error) {
    if (error.code === 'ENOENT') {
      return;
    }
    throw error;
  }

  try {
    const quarantinedStats = fs.lstatSync(quarantinePath);
    if (!sameFileIdentity(snapshot.stats, quarantinedStats)) {
      try {
        fs.renameSync(quarantinePath, lockPath);
      } catch {
        // Preserve the unexpected replacement for manual recovery.
      }
      throw new Error('Frontend dependency synchronization lock changed.');
    }
    fs.rmSync(quarantinePath, { force: true });
  } catch (error) {
    if (error.code !== 'ENOENT') {
      throw error;
    }
  }
}

function removeOwnedLock(lockPath, token) {
  let snapshot;
  try {
    snapshot = readLockSnapshot(lockPath);
  } catch {
    return;
  }
  if (snapshot.kind !== 'owned' || snapshot.owner.token !== token) {
    return;
  }
  quarantineStaleLock(lockPath, snapshot);
}

function runDependencySyncLockHelper() {
  const lockPath = process.env.VANTAGE_INTERNAL_FRONTEND_SYNC_LOCK_PATH;
  const token = process.env.VANTAGE_INTERNAL_FRONTEND_SYNC_LOCK_TOKEN;
  const readyPath = process.env.VANTAGE_INTERNAL_FRONTEND_SYNC_LOCK_READY_PATH;
  const parentPid = Number(
    process.env.VANTAGE_INTERNAL_FRONTEND_SYNC_LOCK_PARENT_PID,
  );
  if (
    !lockPath
    || !token
    || !readyPath
    || !Number.isSafeInteger(parentPid)
    || parentPid <= 0
    || !process.connected
  ) {
    process.exit(2);
  }

  let cleaned = false;
  function cleanup(exitCode = 0) {
    if (cleaned) {
      return;
    }
    cleaned = true;
    removeOwnedLock(lockPath, token);
    fs.rmSync(readyPath, { force: true });
    process.exit(exitCode);
  }

  try {
    const snapshot = readLockSnapshot(lockPath);
    if (
      snapshot.kind !== 'owned'
      || snapshot.owner.pid !== parentPid
      || snapshot.owner.token !== token
    ) {
      cleanup(2);
      return;
    }
    fs.writeFileSync(readyPath, `${token}\n`, {
      encoding: 'utf8',
      flag: 'wx',
      mode: 0o600,
    });
  } catch {
    cleanup(2);
    return;
  }

  process.once('disconnect', () => cleanup(0));
  process.once('SIGTERM', () => cleanup(0));
  process.once('SIGINT', () => cleanup(0));
  const parentWatcher = setInterval(() => {
    if (!processIsAlive(parentPid)) {
      cleanup(0);
    }
  }, 250);
  parentWatcher.unref();
}

function createOwnedLock(lockPath, token) {
  let descriptor;
  try {
    descriptor = fs.openSync(lockPath, 'wx', 0o600);
    const owner = {
      schemaVersion: 1,
      pid: process.pid,
      token,
      createdAtMilliseconds: Date.now(),
    };
    fs.writeFileSync(descriptor, `${JSON.stringify(owner)}\n`, 'utf8');
    fs.fsyncSync(descriptor);
    const openedStats = fs.fstatSync(descriptor);
    const pathStats = fs.lstatSync(lockPath);
    validateLockFileStats(openedStats);
    validateLockFileStats(pathStats);
    if (!sameFileIdentity(openedStats, pathStats)) {
      throw new Error('Frontend dependency synchronization lock changed.');
    }
    return { descriptor, stats: openedStats };
  } catch (error) {
    if (descriptor !== undefined) {
      fs.closeSync(descriptor);
    }
    throw error;
  }
}

function startDependencySyncLockHelper({ lockPath, token, deadline }) {
  const readyPath = `${lockPath}.${token}.ready`;
  const helper = spawn(
    process.execPath,
    [__filename, DEPENDENCY_SYNC_LOCK_HELPER_ARGUMENT],
    {
      env: {
        ...process.env,
        VANTAGE_INTERNAL_FRONTEND_SYNC_LOCK_PATH: lockPath,
        VANTAGE_INTERNAL_FRONTEND_SYNC_LOCK_TOKEN: token,
        VANTAGE_INTERNAL_FRONTEND_SYNC_LOCK_READY_PATH: readyPath,
        VANTAGE_INTERNAL_FRONTEND_SYNC_LOCK_PARENT_PID: String(process.pid),
      },
      stdio: ['ignore', 'ignore', 'ignore', 'ipc'],
      windowsHide: true,
    },
  );
  helper.on('error', () => {
    // Synchronous acquisition observes helper failure through its readiness lease.
  });
  const helperStartDeadline = Math.min(
    deadline,
    performance.now() + DEPENDENCY_SYNC_LOCK_HELPER_START_TIMEOUT_MILLISECONDS,
  );

  while (true) {
    try {
      if (fs.readFileSync(readyPath, 'utf8').trim() === token) {
        return { helper, readyPath };
      }
      throw new Error('Frontend dependency synchronization lock helper failed.');
    } catch (error) {
      if (error.code !== 'ENOENT') {
        helper.kill();
        throw error;
      }
    }
    if (!processIsAlive(helper.pid)) {
      helper.kill();
      throw new Error('Frontend dependency synchronization lock helper failed.');
    }
    const remaining = helperStartDeadline - performance.now();
    if (remaining <= 0) {
      helper.kill();
      throw new Error(
        'Timed out waiting for frontend dependency synchronization lock.',
      );
    }
    sleepSynchronously(Math.min(
      DEPENDENCY_SYNC_LOCK_POLL_MILLISECONDS,
      remaining,
    ));
  }
}

function acquireDependencySyncLockRaw({
  webappRoot,
  timeoutMilliseconds = DEFAULT_DEPENDENCY_SYNC_LOCK_TIMEOUT_MILLISECONDS,
}) {
  if (!Number.isFinite(timeoutMilliseconds) || timeoutMilliseconds < 0) {
    throw new Error('Frontend dependency synchronization lock timeout is invalid.');
  }
  const lockPath = dependencySyncLockPath(webappRoot);
  const deadline = performance.now() + timeoutMilliseconds;

  while (true) {
    const token = crypto.randomBytes(16).toString('hex');
    let ownedLock;
    try {
      ownedLock = createOwnedLock(lockPath, token);
    } catch (error) {
      if (error.code !== 'EEXIST') {
        throw error;
      }
    }

    if (ownedLock) {
      let helperState;
      try {
        helperState = startDependencySyncLockHelper({
          lockPath,
          token,
          deadline,
        });
      } catch (error) {
        fs.closeSync(ownedLock.descriptor);
        removeOwnedLock(lockPath, token);
        throw error;
      }
      let released = false;
      return {
        path: lockPath,
        release() {
          if (released) {
            return;
          }
          released = true;
          fs.closeSync(ownedLock.descriptor);
          removeOwnedLock(lockPath, token);
          fs.rmSync(helperState.readyPath, { force: true });
          if (helperState.helper.connected) {
            helperState.helper.disconnect();
          }
          helperState.helper.unref();
        },
      };
    }

    const snapshot = readLockSnapshot(lockPath);
    if (snapshot.kind === 'missing') {
      continue;
    }
    const lockIsActive = snapshot.kind === 'owned'
      && processIsAlive(snapshot.owner.pid);
    const initializingLockIsRecent = snapshot.kind === 'initializing'
      && Date.now() - snapshot.stats.mtimeMs
        < DEPENDENCY_SYNC_LOCK_INITIALIZATION_GRACE_MILLISECONDS;
    if (!lockIsActive && !initializingLockIsRecent) {
      quarantineStaleLock(lockPath, snapshot);
      continue;
    }

    const remaining = deadline - performance.now();
    if (remaining <= 0) {
      throw new Error(
        'Timed out waiting for frontend dependency synchronization lock.',
      );
    }
    sleepSynchronously(Math.min(
      DEPENDENCY_SYNC_LOCK_POLL_MILLISECONDS,
      remaining,
    ));
  }
}

function acquireDependencySyncLock(options) {
  try {
    const lock = acquireDependencySyncLockRaw(options);
    return {
      release() {
        try {
          lock.release();
        } catch (error) {
          throw sanitizedDependencyLockError(error);
        }
      },
    };
  } catch (error) {
    throw sanitizedDependencyLockError(error);
  }
}

function currentRuntime() {
  return {
    nodeVersion: process.versions.node,
    nodeModulesAbi: process.versions.modules,
    platform: process.platform,
    arch: process.arch,
  };
}

function buildDesiredState({ webappRoot, runtime = currentRuntime() }) {
  const packageLockPath = path.join(webappRoot, 'package-lock.json');
  const lockContents = fs.readFileSync(packageLockPath);

  return {
    packageLockSha256: crypto
      .createHash('sha256')
      .update(lockContents)
      .digest('hex'),
    nodeVersion: runtime.nodeVersion,
    nodeModulesAbi: runtime.nodeModulesAbi,
    platform: runtime.platform,
    arch: runtime.arch,
  };
}

function compareText(left, right) {
  if (left < right) {
    return -1;
  }
  if (left > right) {
    return 1;
  }
  return 0;
}

function isPhysicalDirectory(entry, absolutePath, fileSystem) {
  if (entry.isSymbolicLink()) {
    return false;
  }
  if (entry.isDirectory()) {
    return true;
  }
  try {
    const stats = fileSystem.lstatSync(absolutePath);
    return stats.isDirectory() && !stats.isSymbolicLink();
  } catch {
    return false;
  }
}

function scanInstalledPackages({ webappRoot, fileSystem = fs }) {
  const rootNodeModules = path.join(path.resolve(webappRoot), 'node_modules');
  if (!fileSystem.existsSync(rootNodeModules)) {
    return [];
  }

  const installedPackages = [];
  const pendingNodeModules = [{
    absolutePath: rootNodeModules,
    relativePrefix: '',
  }];
  const visitedNodeModules = new Set();

  function recordPackage(packageDirectory, relativePackagePath) {
    let metadata;
    try {
      metadata = JSON.parse(
        fileSystem.readFileSync(
          path.join(packageDirectory, 'package.json'),
          'utf8',
        ),
      );
    } catch {
      throw new Error(
        `Invalid installed package metadata: ${relativePackagePath}`,
      );
    }
    if (
      typeof metadata.name !== 'string'
      || metadata.name.length === 0
      || typeof metadata.version !== 'string'
      || metadata.version.length === 0
    ) {
      throw new Error(
        `Incomplete installed package metadata: ${relativePackagePath}`,
      );
    }

    installedPackages.push({
      path: relativePackagePath,
      name: metadata.name,
      version: metadata.version,
    });
    pendingNodeModules.push({
      absolutePath: path.join(packageDirectory, 'node_modules'),
      relativePrefix: `${relativePackagePath}/node_modules`,
    });
  }

  while (pendingNodeModules.length > 0) {
    const current = pendingNodeModules.pop();
    if (!fileSystem.existsSync(current.absolutePath)) {
      continue;
    }
    const currentStats = fileSystem.lstatSync(current.absolutePath);
    if (!currentStats.isDirectory() || currentStats.isSymbolicLink()) {
      continue;
    }

    const canonicalPath = fileSystem.realpathSync(current.absolutePath);
    if (visitedNodeModules.has(canonicalPath)) {
      continue;
    }
    visitedNodeModules.add(canonicalPath);

    const entries = fileSystem
      .readdirSync(current.absolutePath, { withFileTypes: true })
      .sort((left, right) => compareText(left.name, right.name));
    for (const entry of entries) {
      if (entry.name.startsWith('.')) {
        continue;
      }
      const entryPath = path.join(current.absolutePath, entry.name);
      if (!isPhysicalDirectory(entry, entryPath, fileSystem)) {
        continue;
      }

      if (entry.name.startsWith('@')) {
        const scopedEntries = fileSystem
          .readdirSync(entryPath, { withFileTypes: true })
          .sort((left, right) => compareText(left.name, right.name));
        for (const scopedEntry of scopedEntries) {
          const scopedPath = path.join(entryPath, scopedEntry.name);
          if (!isPhysicalDirectory(scopedEntry, scopedPath, fileSystem)) {
            continue;
          }
          const relativePackagePath = current.relativePrefix
            ? `${current.relativePrefix}/${entry.name}/${scopedEntry.name}`
            : `${entry.name}/${scopedEntry.name}`;
          recordPackage(scopedPath, relativePackagePath);
        }
        continue;
      }

      const relativePackagePath = current.relativePrefix
        ? `${current.relativePrefix}/${entry.name}`
        : entry.name;
      recordPackage(entryPath, relativePackagePath);
    }
  }

  return installedPackages.sort((left, right) => compareText(left.path, right.path));
}

function readState(statePath) {
  try {
    return JSON.parse(fs.readFileSync(statePath, 'utf8'));
  } catch {
    return null;
  }
}

function stateMatches(actual, desired) {
  return actual !== null
    && Array.isArray(actual.installedPackages)
    && STATE_FIELDS.every((field) => actual[field] === desired[field]);
}

function installedPackagesMatch(actual, expected) {
  return Array.isArray(actual)
    && actual.length === expected.length
    && actual.every((entry, index) => (
      entry.path === expected[index].path
      && entry.name === expected[index].name
      && entry.version === expected[index].version
    ));
}

function writeStateAtomically(
  statePath,
  state,
  {
    fileSystem = fs,
    tempSuffix = `${process.pid}-${Date.now()}-${crypto.randomBytes(6).toString('hex')}`,
  } = {},
) {
  const tempPath = `${statePath}.${tempSuffix}.tmp`;
  fileSystem.mkdirSync(path.dirname(statePath), { recursive: true });
  try {
    fileSystem.writeFileSync(
      tempPath,
      `${JSON.stringify(state, null, 2)}\n`,
      { encoding: 'utf8', flag: 'wx' },
    );
    fileSystem.renameSync(tempPath, statePath);
  } catch (error) {
    fileSystem.rmSync(tempPath, { force: true });
    throw error;
  }
}

function resolveNpmExecution({
  args,
  platform = process.platform,
  nodeExecutable = process.execPath,
  npmCliPath = null,
  env = process.env,
  fileSystem = fs,
}) {
  if (platform !== 'win32') {
    return { command: 'npm', args };
  }

  const resolvedNpmCliPath = npmCliPath
    || env.npm_execpath
    || path.join(
      path.dirname(nodeExecutable),
      'node_modules',
      'npm',
      'bin',
      'npm-cli.js',
    );
  if (!fileSystem.existsSync(resolvedNpmCliPath)) {
    throw new Error(`Unable to locate npm CLI at ${resolvedNpmCliPath}`);
  }
  return {
    command: nodeExecutable,
    args: [resolvedNpmCliPath, ...args],
  };
}

function defaultRunCommand(command, args, options) {
  const execution = command === 'npm'
    ? resolveNpmExecution({ args, env: options.env })
    : { command, args };
  const result = spawnSync(execution.command, execution.args, {
    cwd: options.cwd,
    env: options.env,
    stdio: 'inherit',
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} failed with exit code ${result.status}`);
  }
}

function runNpmCiWithFallback({
  npmCommand,
  webappRoot,
  env,
  runCommand,
  logger,
}) {
  try {
    runCommand(npmCommand, ['ci'], { cwd: webappRoot, env });
    return;
  } catch (error) {
    const fallback = env.VANTAGE_ELECTRON_MIRROR_FALLBACK;
    if (env.ELECTRON_MIRROR || !fallback) {
      throw error;
    }

    logger.warn(`Retrying npm ci with Electron mirror fallback: ${fallback}`);
    runCommand(npmCommand, ['ci'], {
      cwd: webappRoot,
      env: { ...env, ELECTRON_MIRROR: fallback },
    });
  }
}

function synchronizeDependenciesUnlocked({
  webappRoot,
  runtime = currentRuntime(),
  env = process.env,
  force = env.VANTAGE_FORCE_FRONTEND_DEPS === '1',
  invalidateStampPath = null,
  runCommand = defaultRunCommand,
  logger = console,
}) {
  const resolvedWebappRoot = path.resolve(webappRoot);
  const statePath = path.join(
    resolvedWebappRoot,
    'node_modules',
    STATE_FILE_NAME,
  );
  const desiredState = buildDesiredState({
    webappRoot: resolvedWebappRoot,
    runtime,
  });
  const npmCommand = 'npm';
  const commandOptions = { cwd: resolvedWebappRoot, env };

  const savedState = readState(statePath);
  if (!force && stateMatches(savedState, desiredState)) {
    try {
      runCommand(npmCommand, ['ls', '--depth=0'], commandOptions);
      const installedPackages = scanInstalledPackages({
        webappRoot: resolvedWebappRoot,
      });
      if (installedPackagesMatch(savedState.installedPackages, installedPackages)) {
        return {
          synchronized: false,
          state: { ...desiredState, installedPackages },
        };
      }
      logger.warn('Frontend dependency closure changed; running a clean sync.');
    } catch {
      logger.warn('Frontend dependency validation failed; running a clean sync.');
    }
  }

  fs.rmSync(statePath, { force: true });
  if (invalidateStampPath) {
    fs.rmSync(invalidateStampPath, { force: true });
  }

  runNpmCiWithFallback({
    npmCommand,
    webappRoot: resolvedWebappRoot,
    env,
    runCommand,
    logger,
  });
  runCommand(npmCommand, ['ls', '--depth=0'], commandOptions);
  const installedPackages = scanInstalledPackages({
    webappRoot: resolvedWebappRoot,
  });
  const synchronizedState = { ...desiredState, installedPackages };
  writeStateAtomically(statePath, synchronizedState);
  return { synchronized: true, state: synchronizedState };
}

function synchronizeDependencies(options) {
  const {
    webappRoot,
    lockTimeoutMilliseconds = DEFAULT_DEPENDENCY_SYNC_LOCK_TIMEOUT_MILLISECONDS,
  } = options;
  const lock = acquireDependencySyncLock({
    webappRoot,
    timeoutMilliseconds: lockTimeoutMilliseconds,
  });
  try {
    return synchronizeDependenciesUnlocked(options);
  } finally {
    lock.release();
  }
}

function parseArguments(argv) {
  const parsed = {
    webappRoot: path.resolve(__dirname, '..'),
    invalidateStampPath: null,
    force: undefined,
    lockTimeoutMilliseconds: DEFAULT_DEPENDENCY_SYNC_LOCK_TIMEOUT_MILLISECONDS,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--webapp-root') {
      parsed.webappRoot = path.resolve(argv[++index]);
    } else if (argument === '--invalidate-stamp') {
      parsed.invalidateStampPath = path.resolve(argv[++index]);
    } else if (argument === '--force') {
      parsed.force = true;
    } else if (argument === '--lock-timeout-seconds') {
      const timeoutSeconds = Number(argv[++index]);
      if (!Number.isFinite(timeoutSeconds) || timeoutSeconds < 0) {
        throw new Error('Frontend dependency synchronization lock timeout is invalid.');
      }
      parsed.lockTimeoutMilliseconds = timeoutSeconds * 1000;
    } else {
      throw new Error(`Unknown argument: ${argument}`);
    }
  }

  return parsed;
}

function main(argv = process.argv.slice(2)) {
  const options = parseArguments(argv);
  const result = synchronizeDependencies(options);
  if (result.synchronized) {
    console.log('Frontend dependencies synchronized and validated.');
  } else {
    console.log('Frontend dependencies already synchronized and validated.');
  }
}

if (require.main === module) {
  if (process.argv[2] === DEPENDENCY_SYNC_LOCK_HELPER_ARGUMENT) {
    runDependencySyncLockHelper();
  } else {
    try {
      main();
    } catch (error) {
      console.error(`Frontend dependency synchronization failed: ${error.message}`);
      process.exitCode = 1;
    }
  }
}

module.exports = {
  DEFAULT_DEPENDENCY_SYNC_LOCK_TIMEOUT_MILLISECONDS,
  DEPENDENCY_SYNC_LOCK_FILE_NAME,
  STATE_FILE_NAME,
  acquireDependencySyncLock,
  buildDesiredState,
  dependencySyncLockPath,
  main,
  parseArguments,
  resolveNpmExecution,
  scanInstalledPackages,
  stateMatches,
  synchronizeDependencies,
  writeStateAtomically,
};

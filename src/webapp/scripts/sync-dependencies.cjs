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

function isDependencySyncLockLeaseError(error) {
  return error instanceof Error
    && error.message === (
      'Frontend dependency synchronization lock lease was lost.'
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

const CHOOSING_LEASE_PATTERN = /^choosing-(\d+)-([a-f0-9]{32})\.json$/u;
const TICKET_LEASE_PATTERN = /^ticket-(\d{16})-(\d+)-([a-f0-9]{32})\.json$/u;

function validateLockFileStats(stats) {
  if (!stats.isFile() || stats.isSymbolicLink() || stats.nlink !== 1) {
    throw new Error('Frontend dependency synchronization lock is unsafe.');
  }
}

function validateLockDirectoryStats(stats) {
  if (!stats.isDirectory() || stats.isSymbolicLink()) {
    throw new Error('Frontend dependency synchronization lock is unsafe.');
  }
}

function assertLockDirectoryIdentity(lockDirectory, expectedStats) {
  let currentStats;
  try {
    currentStats = fs.lstatSync(lockDirectory);
    validateLockDirectoryStats(currentStats);
  } catch {
    throw new Error(
      'Frontend dependency synchronization lock lease was lost.',
    );
  }
  if (!sameFileIdentity(expectedStats, currentStats)) {
    throw new Error(
      'Frontend dependency synchronization lock lease was lost.',
    );
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
        (candidate.schemaVersion === 1 || candidate.schemaVersion === 2)
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

function removeUniqueLeaseFile(leasePath, snapshot) {
  let currentStats;
  try {
    currentStats = fs.lstatSync(leasePath);
  } catch (error) {
    if (error.code === 'ENOENT') {
      return false;
    }
    throw error;
  }
  if (!sameFileIdentity(snapshot.stats, currentStats)) {
    return false;
  }
  try {
    fs.unlinkSync(leasePath);
    return true;
  } catch (error) {
    if (error.code === 'ENOENT' || error.code === 'EISDIR' || error.code === 'EPERM') {
      return false;
    }
    throw error;
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
  removeUniqueLeaseFile(lockPath, snapshot);
}

function assertOwnedLock({
  lockDirectory,
  lockDirectoryStats,
  lockPath,
  token,
  descriptor,
  expectedStats,
}) {
  assertLockDirectoryIdentity(lockDirectory, lockDirectoryStats);
  let descriptorStats;
  let snapshot;
  try {
    descriptorStats = fs.fstatSync(descriptor);
    snapshot = readLockSnapshot(lockPath);
  } catch {
    throw new Error(
      'Frontend dependency synchronization lock lease was lost.',
    );
  }
  if (
    !sameFileIdentity(expectedStats, descriptorStats)
    || snapshot.kind !== 'owned'
    || snapshot.owner.pid !== process.pid
    || snapshot.owner.token !== token
    || !sameFileIdentity(expectedStats, snapshot.stats)
  ) {
    throw new Error(
      'Frontend dependency synchronization lock lease was lost.',
    );
  }
}

function parseLeaseEntryName(name) {
  let match = CHOOSING_LEASE_PATTERN.exec(name);
  if (match) {
    return {
      phase: 'choosing',
      pid: Number(match[1]),
      token: match[2],
      ticket: null,
    };
  }
  match = TICKET_LEASE_PATTERN.exec(name);
  if (!match) {
    return null;
  }
  return {
    phase: 'ticket',
    ticket: Number(match[1]),
    pid: Number(match[2]),
    token: match[3],
  };
}

function scanLiveLeaseEntries(lockDirectory, lockDirectoryStats) {
  assertLockDirectoryIdentity(lockDirectory, lockDirectoryStats);
  const liveEntries = [];
  const directoryEntries = fs.readdirSync(lockDirectory, {
    withFileTypes: true,
  });
  for (const directoryEntry of directoryEntries) {
    const parsed = parseLeaseEntryName(directoryEntry.name);
    if (parsed === null) {
      continue;
    }
    const leasePath = path.join(lockDirectory, directoryEntry.name);
    let snapshot;
    try {
      snapshot = readLockSnapshot(leasePath);
    } catch {
      throw new Error('Frontend dependency synchronization lock is unsafe.');
    }
    if (snapshot.kind === 'missing') {
      continue;
    }
    const ownerMatchesName = snapshot.kind === 'owned'
      && snapshot.owner.pid === parsed.pid
      && snapshot.owner.token === parsed.token;
    if (ownerMatchesName && processIsAlive(parsed.pid)) {
      liveEntries.push({ ...parsed, path: leasePath, snapshot });
      continue;
    }
    const initializingLeaseIsRecent = snapshot.kind === 'initializing'
      && Date.now() - snapshot.stats.mtimeMs
        < DEPENDENCY_SYNC_LOCK_INITIALIZATION_GRACE_MILLISECONDS;
    if (initializingLeaseIsRecent) {
      liveEntries.push({
        ...parsed,
        phase: 'choosing',
        path: leasePath,
        snapshot,
      });
      continue;
    }
    removeUniqueLeaseFile(leasePath, snapshot);
  }
  assertLockDirectoryIdentity(lockDirectory, lockDirectoryStats);
  return liveEntries;
}

function ensureLockDirectory(lockDirectory) {
  try {
    fs.mkdirSync(lockDirectory, { mode: 0o700 });
    const createdStats = fs.lstatSync(lockDirectory);
    validateLockDirectoryStats(createdStats);
    return createdStats;
  } catch (error) {
    if (error.code !== 'EEXIST') {
      throw error;
    }
  }

  let existingStats;
  try {
    existingStats = fs.lstatSync(lockDirectory);
  } catch (error) {
    if (error.code === 'ENOENT') {
      return null;
    }
    throw error;
  }
  if (existingStats.isDirectory() && !existingStats.isSymbolicLink()) {
    validateLockDirectoryStats(existingStats);
    return existingStats;
  }
  validateLockFileStats(existingStats);
  let legacySnapshot;
  try {
    legacySnapshot = readLockSnapshot(lockDirectory);
  } catch (error) {
    try {
      const replacementStats = fs.lstatSync(lockDirectory);
      if (
        replacementStats.isDirectory()
        && !replacementStats.isSymbolicLink()
      ) {
        validateLockDirectoryStats(replacementStats);
        return replacementStats;
      }
    } catch (replacementError) {
      if (replacementError.code === 'ENOENT') {
        return null;
      }
    }
    throw error;
  }
  if (legacySnapshot.kind === 'missing') {
    return null;
  }
  const legacyOwnerIsAlive = legacySnapshot.kind === 'owned'
    && processIsAlive(legacySnapshot.owner.pid);
  const initializingLegacyIsRecent = legacySnapshot.kind === 'initializing'
    && Date.now() - legacySnapshot.stats.mtimeMs
      < DEPENDENCY_SYNC_LOCK_INITIALIZATION_GRACE_MILLISECONDS;
  if (legacyOwnerIsAlive || initializingLegacyIsRecent) {
    return null;
  }
  removeUniqueLeaseFile(lockDirectory, legacySnapshot);
  return null;
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
      schemaVersion: 2,
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
  const lockDirectory = dependencySyncLockPath(webappRoot);
  const deadline = performance.now() + timeoutMilliseconds;
  let lockDirectoryStats = null;
  while (true) {
    lockDirectoryStats = ensureLockDirectory(lockDirectory);
    if (lockDirectoryStats !== null) {
      break;
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

  const token = crypto.randomBytes(16).toString('hex');
  const choosingPath = path.join(
    lockDirectory,
    `choosing-${process.pid}-${token}.json`,
  );
  const choosingLock = createOwnedLock(choosingPath, token);
  let ticketPath = null;
  let ticketLock = null;
  let helperState = null;

  function cleanupAttempt() {
    if (choosingLock.descriptor !== null) {
      fs.closeSync(choosingLock.descriptor);
      choosingLock.descriptor = null;
    }
    removeOwnedLock(choosingPath, token);
    if (ticketLock?.descriptor !== null && ticketLock?.descriptor !== undefined) {
      fs.closeSync(ticketLock.descriptor);
      ticketLock.descriptor = null;
    }
    if (ticketPath !== null) {
      removeOwnedLock(ticketPath, token);
    }
    if (helperState !== null) {
      fs.rmSync(helperState.readyPath, { force: true });
      if (helperState.helper.connected) {
        helperState.helper.disconnect();
      }
      helperState.helper.unref();
    }
  }

  try {
    const existingEntries = scanLiveLeaseEntries(
      lockDirectory,
      lockDirectoryStats,
    );
    const highestTicket = existingEntries.reduce(
      (highest, entry) => (
        entry.phase === 'ticket' ? Math.max(highest, entry.ticket) : highest
      ),
      0,
    );
    if (highestTicket >= Number.MAX_SAFE_INTEGER) {
      throw new Error('Frontend dependency synchronization lock ticket overflow.');
    }
    const ticket = highestTicket + 1;
    ticketPath = path.join(
      lockDirectory,
      `ticket-${String(ticket).padStart(16, '0')}-${process.pid}-${token}.json`,
    );
    ticketLock = createOwnedLock(ticketPath, token);
    fs.closeSync(choosingLock.descriptor);
    choosingLock.descriptor = null;
    removeOwnedLock(choosingPath, token);
    helperState = startDependencySyncLockHelper({
      lockPath: ticketPath,
      token,
      deadline,
    });

    while (true) {
      assertOwnedLock({
        lockDirectory,
        lockDirectoryStats,
        lockPath: ticketPath,
        token,
        descriptor: ticketLock.descriptor,
        expectedStats: ticketLock.stats,
      });
      const liveEntries = scanLiveLeaseEntries(
        lockDirectory,
        lockDirectoryStats,
      );
      const anotherProcessIsChoosing = liveEntries.some(
        (entry) => entry.phase === 'choosing',
      );
      const tickets = liveEntries
        .filter((entry) => entry.phase === 'ticket')
        .sort((left, right) => (
          left.ticket - right.ticket || compareText(left.token, right.token)
        ));
      if (
        !anotherProcessIsChoosing
        && tickets.length > 0
        && tickets[0].path === ticketPath
      ) {
        break;
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
  } catch (error) {
    cleanupAttempt();
    throw error;
  }

  let released = false;
  return {
    path: ticketPath,
    assertOwned() {
      assertOwnedLock({
        lockDirectory,
        lockDirectoryStats,
        lockPath: ticketPath,
        token,
        descriptor: ticketLock.descriptor,
        expectedStats: ticketLock.stats,
      });
    },
    release() {
      if (released) {
        return;
      }
      released = true;
      cleanupAttempt();
    },
  };
}

function acquireDependencySyncLock(options) {
  try {
    const lock = acquireDependencySyncLockRaw(options);
    return {
      assertOwned() {
        try {
          lock.assertOwned();
        } catch (error) {
          throw sanitizedDependencyLockError(error);
        }
      },
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
    beforeRename = () => {},
    publishRaceHook = () => {},
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
    beforeRename();
    publishRaceHook();
    beforeRename();
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
    if (isDependencySyncLockLeaseError(error)) {
      throw error;
    }
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
  assertLockOwned = () => {},
  statePublishRaceHook = () => {},
}) {
  assertLockOwned();
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
  assertLockOwned();
  const npmCommand = 'npm';
  const commandOptions = { cwd: resolvedWebappRoot, env };
  const guardedRunCommand = (...args) => {
    assertLockOwned();
    try {
      return runCommand(...args);
    } finally {
      assertLockOwned();
    }
  };
  const guardedInstalledPackageScan = () => {
    assertLockOwned();
    const installedPackages = scanInstalledPackages({
      webappRoot: resolvedWebappRoot,
    });
    assertLockOwned();
    return installedPackages;
  };

  assertLockOwned();
  const savedState = readState(statePath);
  assertLockOwned();
  if (!force && stateMatches(savedState, desiredState)) {
    try {
      guardedRunCommand(npmCommand, ['ls', '--depth=0'], commandOptions);
      const installedPackages = guardedInstalledPackageScan();
      if (installedPackagesMatch(savedState.installedPackages, installedPackages)) {
        assertLockOwned();
        return {
          synchronized: false,
          state: { ...desiredState, installedPackages },
        };
      }
      logger.warn('Frontend dependency closure changed; running a clean sync.');
    } catch (error) {
      if (isDependencySyncLockLeaseError(error)) {
        throw error;
      }
      logger.warn('Frontend dependency validation failed; running a clean sync.');
    }
  }

  assertLockOwned();
  fs.rmSync(statePath, { force: true });
  assertLockOwned();
  if (invalidateStampPath) {
    assertLockOwned();
    fs.rmSync(invalidateStampPath, { force: true });
    assertLockOwned();
  }

  runNpmCiWithFallback({
    npmCommand,
    webappRoot: resolvedWebappRoot,
    env,
    runCommand: guardedRunCommand,
    logger,
  });
  guardedRunCommand(npmCommand, ['ls', '--depth=0'], commandOptions);
  const installedPackages = guardedInstalledPackageScan();
  const synchronizedState = { ...desiredState, installedPackages };
  assertLockOwned();
  writeStateAtomically(statePath, synchronizedState, {
    beforeRename: assertLockOwned,
    publishRaceHook: statePublishRaceHook,
  });
  assertLockOwned();
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
    lock.assertOwned();
    const result = synchronizeDependenciesUnlocked({
      ...options,
      assertLockOwned: () => lock.assertOwned(),
    });
    lock.assertOwned();
    return result;
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

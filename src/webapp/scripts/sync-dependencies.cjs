'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const STATE_FILE_NAME = '.vantage-package-lock-state.json';
const STATE_FIELDS = Object.freeze([
  'packageLockSha256',
  'nodeVersion',
  'nodeModulesAbi',
  'platform',
  'arch',
]);

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

function synchronizeDependencies({
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

function parseArguments(argv) {
  const parsed = {
    webappRoot: path.resolve(__dirname, '..'),
    invalidateStampPath: null,
    force: undefined,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--webapp-root') {
      parsed.webappRoot = path.resolve(argv[++index]);
    } else if (argument === '--invalidate-stamp') {
      parsed.invalidateStampPath = path.resolve(argv[++index]);
    } else if (argument === '--force') {
      parsed.force = true;
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
  try {
    main();
  } catch (error) {
    console.error(`Frontend dependency synchronization failed: ${error.message}`);
    process.exitCode = 1;
  }
}

module.exports = {
  STATE_FILE_NAME,
  buildDesiredState,
  main,
  parseArguments,
  resolveNpmExecution,
  scanInstalledPackages,
  stateMatches,
  synchronizeDependencies,
  writeStateAtomically,
};

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

function readState(statePath) {
  try {
    return JSON.parse(fs.readFileSync(statePath, 'utf8'));
  } catch {
    return null;
  }
}

function stateMatches(actual, desired) {
  return actual !== null
    && STATE_FIELDS.every((field) => actual[field] === desired[field]);
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

  if (!force && stateMatches(readState(statePath), desiredState)) {
    try {
      runCommand(npmCommand, ['ls', '--depth=0'], commandOptions);
      return { synchronized: false, state: desiredState };
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
  writeStateAtomically(statePath, desiredState);
  return { synchronized: true, state: desiredState };
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
  stateMatches,
  synchronizeDependencies,
  writeStateAtomically,
};

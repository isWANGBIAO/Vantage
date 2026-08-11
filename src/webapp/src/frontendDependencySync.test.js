import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import {
  chmodSync,
  existsSync,
  linkSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const {
  DEPENDENCY_SYNC_LOCK_FILE_NAME,
  STATE_FILE_NAME,
  buildDesiredState,
  dependencySyncLockPath,
  resolveNpmExecution,
  scanInstalledPackages,
  synchronizeDependencies,
  writeStateAtomically,
} = require('../scripts/sync-dependencies.cjs');

const SYNC_SCRIPT_PATH = fileURLToPath(
  new URL('../scripts/sync-dependencies.cjs', import.meta.url),
);

const TEST_RUNTIME = {
  nodeVersion: '24.18.0',
  nodeModulesAbi: '137',
  platform: 'win32',
  arch: 'x64',
};
const SILENT_LOGGER = { warn() {} };

function createWebappFixture(lockContents = '{"lockfileVersion":3}\n') {
  const webappRoot = mkdtempSync(path.join(tmpdir(), 'vantage-frontend-sync-'));
  writeFileSync(path.join(webappRoot, 'package-lock.json'), lockContents, 'utf8');
  mkdirSync(path.join(webappRoot, 'node_modules'), { recursive: true });
  return webappRoot;
}

function statePathFor(webappRoot) {
  return path.join(webappRoot, 'node_modules', STATE_FILE_NAME);
}

function writePackage(webappRoot, relativePackagePath, name, version) {
  const packageDirectory = path.join(
    webappRoot,
    'node_modules',
    ...relativePackagePath.split('/'),
  );
  mkdirSync(packageDirectory, { recursive: true });
  writeFileSync(
    path.join(packageDirectory, 'package.json'),
    `${JSON.stringify({ name, version })}\n`,
    'utf8',
  );
  return packageDirectory;
}

function buildStampedState(webappRoot, runtime = TEST_RUNTIME) {
  return {
    ...buildDesiredState({ webappRoot, runtime }),
    installedPackages: scanInstalledPackages({ webappRoot }),
  };
}

function writeDesiredState(webappRoot, runtime = TEST_RUNTIME) {
  const state = buildStampedState(webappRoot, runtime);
  writeFileSync(statePathFor(webappRoot), `${JSON.stringify(state)}\n`, 'utf8');
  return state;
}

function withFixture(run) {
  const webappRoot = createWebappFixture();
  try {
    return run(webappRoot);
  } finally {
    rmSync(webappRoot, { recursive: true, force: true });
  }
}

function sleep(milliseconds) {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}

async function waitFor(predicate, message, timeoutMilliseconds = 5000) {
  const deadline = Date.now() + timeoutMilliseconds;
  while (Date.now() < deadline) {
    if (predicate()) {
      return;
    }
    await sleep(20);
  }
  assert.fail(message);
}

async function removeFixtureWhenIdle(webappRoot) {
  await waitFor(
    () => {
      try {
        rmSync(webappRoot, { recursive: true, force: true });
        return true;
      } catch (error) {
        if (error?.code === 'EPERM') {
          return false;
        }
        throw error;
      }
    },
    'the command fixture remained busy after descendant cleanup',
  );
}

function readEventLines(eventsPath) {
  if (!existsSync(eventsPath)) {
    return [];
  }
  return readFileSync(eventsPath, 'utf8').trim().split(/\r?\n/u).filter(Boolean);
}

function listCommandGuardianDirectories(webappRoot) {
  const lockPath = dependencySyncLockPath(webappRoot);
  if (!existsSync(lockPath) || !lstatSync(lockPath).isDirectory()) {
    return [];
  }
  return readdirSync(lockPath, { withFileTypes: true })
    .filter((entry) => (
      entry.isDirectory()
      && entry.name.startsWith('command-')
    ))
    .map((entry) => path.join(lockPath, entry.name));
}

function readSurvivingGuardianFiles(directory) {
  try {
    return readdirSync(directory)
      .map((name) => {
        try {
          return readFileSync(path.join(directory, name), 'utf8');
        } catch {
          return '';
        }
      })
      .join('\n');
  } catch {
    return '';
  }
}

function findActiveDependencyLease(lockPath) {
  const lockStats = lstatSync(lockPath);
  if (lockStats.isFile()) {
    return lockPath;
  }
  const tickets = readdirSync(lockPath)
    .filter((name) => /^ticket-.*\.json$/u.test(name));
  assert.equal(tickets.length, 1, `expected one active ticket: ${tickets}`);
  return path.join(lockPath, tickets[0]);
}

function listDependencyLeaseNames(lockPath) {
  if (!existsSync(lockPath) || !lstatSync(lockPath).isDirectory()) {
    return [];
  }
  return readdirSync(lockPath).filter((name) => (
    /^choosing-.*\.json$/u.test(name) || /^ticket-.*\.json$/u.test(name)
  ));
}

function writeSyncWorker(webappRoot) {
  const workerPath = path.join(webappRoot, 'sync-worker.cjs');
  writeFileSync(
    workerPath,
    `'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { synchronizeDependencies } = require(${JSON.stringify(SYNC_SCRIPT_PATH)});
const webappRoot = process.env.WEBAPP_ROOT;
const eventsPath = process.env.EVENTS_PATH;
const releasePath = process.env.RELEASE_PATH;
const workerId = process.env.WORKER_ID;
const waitArray = new Int32Array(new SharedArrayBuffer(4));

function sleepSync(milliseconds) {
  Atomics.wait(waitArray, 0, 0, milliseconds);
}

try {
  while (process.env.START_PATH && !fs.existsSync(process.env.START_PATH)) {
    sleepSync(10);
  }
  synchronizeDependencies({
    webappRoot,
    env: {},
    lockTimeoutMilliseconds: Number(process.env.LOCK_TIMEOUT_MS || 5000),
    invalidateStampPath: process.env.SIGN_STAMP_PATH,
    logger: { warn() {} },
    runCommand(_command, args) {
      if (args[0] === 'ci') {
        fs.appendFileSync(eventsPath, workerId + ':ci:start\\n', 'utf8');
        if (workerId === 'holder') {
          while (!fs.existsSync(releasePath)) {
            sleepSync(10);
          }
        }
        const packageDirectory = path.join(webappRoot, 'node_modules', 'fixture');
        fs.mkdirSync(packageDirectory, { recursive: true });
        fs.writeFileSync(
          path.join(packageDirectory, 'package.json'),
          '{"name":"fixture","version":"1.0.0"}\\n',
          'utf8',
        );
        fs.appendFileSync(eventsPath, workerId + ':ci:end\\n', 'utf8');
      }
    },
  });
  process.exitCode = 0;
} catch (error) {
  process.stderr.write(error.message + '\\n');
  process.exitCode = 1;
}
`,
    'utf8',
  );
  return workerPath;
}

function spawnSyncWorker({
  workerPath,
  webappRoot,
  workerId,
  eventsPath,
  releasePath,
  signStampPath,
  startPath = '',
  lockTimeoutMilliseconds = 5000,
  extraEnv = {},
}) {
  const child = spawn(process.execPath, [workerPath], {
    cwd: webappRoot,
    env: {
      ...process.env,
      WEBAPP_ROOT: webappRoot,
      WORKER_ID: workerId,
      EVENTS_PATH: eventsPath,
      RELEASE_PATH: releasePath,
      SIGN_STAMP_PATH: signStampPath,
      START_PATH: startPath,
      LOCK_TIMEOUT_MS: String(lockTimeoutMilliseconds),
      ...extraEnv,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  let stdout = '';
  let stderr = '';
  child.stdout.setEncoding('utf8');
  child.stderr.setEncoding('utf8');
  child.stdout.on('data', (chunk) => {
    stdout += chunk;
  });
  child.stderr.on('data', (chunk) => {
    stderr += chunk;
  });
  const completion = new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('close', (code, signal) => {
      resolve({ code, signal, stdout, stderr });
    });
  });
  return { child, completion };
}

function writeDefaultCommandSyncWorker(webappRoot) {
  const workerPath = path.join(webappRoot, 'default-command-sync-worker.cjs');
  writeFileSync(
    workerPath,
    `'use strict';
const { synchronizeDependencies } = require(${JSON.stringify(SYNC_SCRIPT_PATH)});

try {
  synchronizeDependencies({
    webappRoot: process.env.WEBAPP_ROOT,
    env: process.env,
    force: true,
    lockTimeoutMilliseconds: Number(process.env.LOCK_TIMEOUT_MS || 5000),
    logger: { warn() {} },
  });
  process.exitCode = 0;
} catch (error) {
  process.stderr.write(error.message + '\\n');
  process.exitCode = 1;
}
`,
    'utf8',
  );
  return workerPath;
}

function writeCrashFixtureNpm(webappRoot) {
  const binDirectory = path.join(webappRoot, 'fake-bin');
  const npmPath = path.join(binDirectory, 'npm');
  mkdirSync(binDirectory, { recursive: true });
  writeFileSync(
    npmPath,
    `#!${process.execPath}
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');

const command = process.argv[2];
const workerId = process.env.WORKER_ID;
const eventsPath = process.env.EVENTS_PATH;
const mutatorPidPath = process.env.MUTATOR_PID_PATH;
const releasePath = process.env.RELEASE_PATH;

function processIsAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === 'EPERM';
  }
}

if (command === 'ci') {
  fs.appendFileSync(eventsPath, workerId + ':ci:start\\n', 'utf8');
  if (workerId === 'holder') {
    const mutator = spawn(
      process.execPath,
      ['-e', 'setInterval(() => {}, 1000)'],
      { detached: process.platform === 'win32', stdio: 'ignore' },
    );
    mutator.unref();
    fs.writeFileSync(mutatorPidPath, String(mutator.pid), 'utf8');
    if (process.env.NORMAL_EXIT_WITH_DESCENDANT !== '1') {
      while (!fs.existsSync(releasePath)) {
        Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10);
      }
      mutator.kill('SIGTERM');
    }
  } else if (fs.existsSync(mutatorPidPath)) {
    const mutatorPid = Number(fs.readFileSync(mutatorPidPath, 'utf8'));
    if (Number.isSafeInteger(mutatorPid) && processIsAlive(mutatorPid)) {
      fs.appendFileSync(eventsPath, workerId + ':overlap\\n', 'utf8');
    }
  }
  const packageDirectory = path.join(
    process.env.WEBAPP_ROOT,
    'node_modules',
    'fixture',
  );
  fs.mkdirSync(packageDirectory, { recursive: true });
  fs.writeFileSync(
    path.join(packageDirectory, 'package.json'),
    '{"name":"fixture","version":"1.0.0"}\\n',
    'utf8',
  );
  fs.appendFileSync(eventsPath, workerId + ':ci:end\\n', 'utf8');
}
`,
    'utf8',
  );
  chmodSync(npmPath, 0o700);
  return { binDirectory, npmPath };
}

test('desired state includes the lock hash and complete Node platform identity', () => {
  withFixture((webappRoot) => {
    const lockContents = readFileSync(
      path.join(webappRoot, 'package-lock.json'),
      'utf8',
    );
    const expectedHash = createHash('sha256').update(lockContents).digest('hex');

    assert.deepEqual(buildDesiredState({ webappRoot, runtime: TEST_RUNTIME }), {
      packageLockSha256: expectedHash,
      nodeVersion: '24.18.0',
      nodeModulesAbi: '137',
      platform: 'win32',
      arch: 'x64',
    });
  });
});

test('Windows executes npm through its JavaScript CLI instead of spawning npm.cmd', () => {
  const execution = resolveNpmExecution({
    args: ['ls', '--depth=0'],
    platform: 'win32',
    nodeExecutable: 'C:\\Node\\node.exe',
    npmCliPath: 'C:\\Node\\node_modules\\npm\\bin\\npm-cli.js',
    fileSystem: { existsSync: () => true },
  });

  assert.deepEqual(execution, {
    command: 'C:\\Node\\node.exe',
    args: [
      'C:\\Node\\node_modules\\npm\\bin\\npm-cli.js',
      'ls',
      '--depth=0',
    ],
  });
});

test('installed package scan is stable across scoped and nested physical packages', () => {
  withFixture((webappRoot) => {
    writePackage(webappRoot, 'zeta', 'zeta', '3.0.0');
    writePackage(webappRoot, '@scope/parent', '@scope/parent', '2.0.0');
    writePackage(
      webappRoot,
      '@scope/parent/node_modules/alpha',
      'alpha',
      '1.0.0',
    );

    assert.deepEqual(scanInstalledPackages({ webappRoot }), [
      {
        path: '@scope/parent',
        name: '@scope/parent',
        version: '2.0.0',
      },
      {
        path: '@scope/parent/node_modules/alpha',
        name: 'alpha',
        version: '1.0.0',
      },
      { path: 'zeta', name: 'zeta', version: '3.0.0' },
    ]);
  });
});

test('installed package scan does not follow a nested symlink loop', (context) => {
  withFixture((webappRoot) => {
    const packageDirectory = writePackage(
      webappRoot,
      'loop-package',
      'loop-package',
      '1.0.0',
    );
    const nestedModules = path.join(packageDirectory, 'node_modules');
    mkdirSync(nestedModules, { recursive: true });
    try {
      symlinkSync(
        path.join(webappRoot, 'node_modules'),
        path.join(nestedModules, 'loop'),
        process.platform === 'win32' ? 'junction' : 'dir',
      );
    } catch (error) {
      context.skip(`symlink creation unavailable: ${error.code}`);
      return;
    }

    assert.deepEqual(scanInstalledPackages({ webappRoot }), [
      {
        path: 'loop-package',
        name: 'loop-package',
        version: '1.0.0',
      },
    ]);
  });
});

test('exact installed version drift forces npm ci even when npm ls succeeds', () => {
  withFixture((webappRoot) => {
    writeFileSync(
      path.join(webappRoot, 'package-lock.json'),
      JSON.stringify({
        lockfileVersion: 3,
        packages: {
          '': { dependencies: { direct: '^1.0.0' } },
          'node_modules/direct': { version: '1.0.1' },
        },
      }),
      'utf8',
    );
    writePackage(webappRoot, 'direct', 'direct', '1.0.1');
    writeDesiredState(webappRoot);
    writePackage(webappRoot, 'direct', 'direct', '1.0.2');
    const calls = [];

    const result = synchronizeDependencies({
      webappRoot,
      runtime: TEST_RUNTIME,
      env: {},
      logger: SILENT_LOGGER,
      runCommand(command, args) {
        calls.push([command, args]);
        if (args[0] === 'ci') {
          writePackage(webappRoot, 'direct', 'direct', '1.0.1');
        }
      },
    });

    assert.equal(result.synchronized, true);
    assert.deepEqual(calls.map(([, args]) => args), [
      ['ls', '--depth=0'],
      ['ci'],
      ['ls', '--depth=0'],
    ]);
    assert.deepEqual(
      JSON.parse(readFileSync(statePathFor(webappRoot), 'utf8')).installedPackages,
      [{ path: 'direct', name: 'direct', version: '1.0.1' }],
    );
  });
});

test('a missing installed package forces npm ci after npm ls succeeds', () => {
  withFixture((webappRoot) => {
    writePackage(webappRoot, 'parent', 'parent', '2.0.0');
    const nestedDirectory = writePackage(
      webappRoot,
      'parent/node_modules/nested',
      'nested',
      '1.0.1',
    );
    writeDesiredState(webappRoot);
    rmSync(nestedDirectory, { recursive: true, force: true });
    const calls = [];

    const result = synchronizeDependencies({
      webappRoot,
      runtime: TEST_RUNTIME,
      env: {},
      logger: SILENT_LOGGER,
      runCommand(command, args) {
        calls.push([command, args]);
        if (args[0] === 'ci') {
          writePackage(
            webappRoot,
            'parent/node_modules/nested',
            'nested',
            '1.0.1',
          );
        }
      },
    });

    assert.equal(result.synchronized, true);
    assert.deepEqual(calls.map(([, args]) => args), [
      ['ls', '--depth=0'],
      ['ci'],
      ['ls', '--depth=0'],
    ]);
  });
});

test('an extra nested installed package forces npm ci after npm ls succeeds', () => {
  withFixture((webappRoot) => {
    writePackage(webappRoot, '@scope/parent', '@scope/parent', '2.0.0');
    writeDesiredState(webappRoot);
    const extraDirectory = writePackage(
      webappRoot,
      '@scope/parent/node_modules/extra',
      'extra',
      '9.0.0',
    );
    const calls = [];

    const result = synchronizeDependencies({
      webappRoot,
      runtime: TEST_RUNTIME,
      env: {},
      logger: SILENT_LOGGER,
      runCommand(command, args) {
        calls.push([command, args]);
        if (args[0] === 'ci') {
          rmSync(extraDirectory, { recursive: true, force: true });
        }
      },
    });

    assert.equal(result.synchronized, true);
    assert.deepEqual(calls.map(([, args]) => args), [
      ['ls', '--depth=0'],
      ['ci'],
      ['ls', '--depth=0'],
    ]);
  });
});

test('legacy state without an installed package closure is never reused', () => {
  withFixture((webappRoot) => {
    const legacyState = buildDesiredState({
      webappRoot,
      runtime: TEST_RUNTIME,
    });
    writeFileSync(
      statePathFor(webappRoot),
      `${JSON.stringify(legacyState)}\n`,
      'utf8',
    );
    const calls = [];

    const result = synchronizeDependencies({
      webappRoot,
      runtime: TEST_RUNTIME,
      env: {},
      runCommand(command, args) {
        calls.push([command, args]);
      },
    });

    assert.equal(result.synchronized, true);
    assert.deepEqual(calls.map(([, args]) => args), [
      ['ci'],
      ['ls', '--depth=0'],
    ]);
    assert.deepEqual(
      JSON.parse(readFileSync(statePathFor(webappRoot), 'utf8')).installedPackages,
      [],
    );
  });
});

test('matching state takes the validated fast path without npm ci', () => {
  withFixture((webappRoot) => {
    const expected = writeDesiredState(webappRoot);
    const calls = [];

    const result = synchronizeDependencies({
      webappRoot,
      runtime: TEST_RUNTIME,
      env: {},
      runCommand(command, args) {
        calls.push([command, args]);
      },
    });

    assert.equal(result.synchronized, false);
    assert.deepEqual(calls.map(([, args]) => args), [['ls', '--depth=0']]);
    assert.deepEqual(
      JSON.parse(readFileSync(statePathFor(webappRoot), 'utf8')),
      expected,
    );
  });
});

test('stale package lock runs npm ci before validating and replacing state', () => {
  withFixture((webappRoot) => {
    writeDesiredState(webappRoot);
    writeFileSync(
      path.join(webappRoot, 'package-lock.json'),
      '{"lockfileVersion":3,"packages":{"":{"version":"2.0.0"}}}\n',
      'utf8',
    );
    const calls = [];

    const result = synchronizeDependencies({
      webappRoot,
      runtime: TEST_RUNTIME,
      env: {},
      runCommand(command, args) {
        calls.push([command, args]);
      },
    });

    assert.equal(result.synchronized, true);
    assert.deepEqual(calls.map(([, args]) => args), [
      ['ci'],
      ['ls', '--depth=0'],
    ]);
    assert.deepEqual(
      JSON.parse(readFileSync(statePathFor(webappRoot), 'utf8')),
      buildStampedState(webappRoot, TEST_RUNTIME),
    );
  });
});

test('invalid npm ls on a matching state forces a clean reinstall', () => {
  withFixture((webappRoot) => {
    writeDesiredState(webappRoot);
    const calls = [];
    let validationAttempts = 0;

    const result = synchronizeDependencies({
      webappRoot,
      runtime: TEST_RUNTIME,
      env: {},
      logger: SILENT_LOGGER,
      runCommand(command, args) {
        calls.push([command, args]);
        if (args[0] === 'ls' && validationAttempts++ === 0) {
          throw new Error('invalid dependency tree');
        }
        if (args[0] === 'ci') {
          assert.equal(existsSync(statePathFor(webappRoot)), false);
        }
      },
    });

    assert.equal(result.synchronized, true);
    assert.deepEqual(calls.map(([, args]) => args), [
      ['ls', '--depth=0'],
      ['ci'],
      ['ls', '--depth=0'],
    ]);
    assert.equal(existsSync(statePathFor(webappRoot)), true);
  });
});

test('failed synchronization leaves no reusable state', () => {
  withFixture((webappRoot) => {
    writeDesiredState(webappRoot);
    writeFileSync(
      path.join(webappRoot, 'package-lock.json'),
      '{"lockfileVersion":3,"changed":true}\n',
      'utf8',
    );

    assert.throws(
      () => synchronizeDependencies({
        webappRoot,
        runtime: TEST_RUNTIME,
        env: {},
        runCommand() {
          throw new Error('npm ci failed');
        },
      }),
      /npm ci failed/,
    );
    assert.equal(existsSync(statePathFor(webappRoot)), false);
  });
});

test('failed post-install npm ls validation leaves no reusable state', () => {
  withFixture((webappRoot) => {
    writeDesiredState(webappRoot);
    writeFileSync(
      path.join(webappRoot, 'package-lock.json'),
      '{"lockfileVersion":3,"changedAfterInstall":true}\n',
      'utf8',
    );
    const calls = [];

    assert.throws(
      () => synchronizeDependencies({
        webappRoot,
        runtime: TEST_RUNTIME,
        env: {},
        runCommand(command, args) {
          calls.push([command, args]);
          if (args[0] === 'ls') {
            throw new Error('post-install validation failed');
          }
        },
      }),
      /post-install validation failed/,
    );
    assert.deepEqual(calls.map(([, args]) => args), [
      ['ci'],
      ['ls', '--depth=0'],
    ]);
    assert.equal(existsSync(statePathFor(webappRoot)), false);
  });
});

test('state is atomically renamed only after dependency validation succeeds', () => {
  withFixture((webappRoot) => {
    const statePath = statePathFor(webappRoot);
    const events = [];
    const fileSystem = {
      mkdirSync(directory, options) {
        events.push(['mkdir', directory, options]);
      },
      writeFileSync(filePath, contents, options) {
        events.push(['write', filePath, contents, options]);
      },
      renameSync(source, destination) {
        events.push(['rename', source, destination]);
      },
      rmSync(filePath, options) {
        events.push(['rm', filePath, options]);
      },
    };

    writeStateAtomically(statePath, { ready: true }, {
      fileSystem,
      tempSuffix: 'test',
    });

    assert.equal(events[1][0], 'write');
    assert.equal(events[1][1], `${statePath}.test.tmp`);
    assert.equal(events[2][0], 'rename');
    assert.deepEqual(events[2].slice(1), [
      `${statePath}.test.tmp`,
      statePath,
    ]);

    const calls = [];
    synchronizeDependencies({
      webappRoot,
      runtime: TEST_RUNTIME,
      env: {},
      runCommand(command, args) {
        calls.push([command, args]);
        if (args[0] === 'ls') {
          assert.equal(existsSync(statePath), false);
        }
      },
    });
    assert.equal(existsSync(statePath), true);
    assert.deepEqual(
      readdirSync(path.dirname(statePath)).filter((name) => name.endsWith('.tmp')),
      [],
    );
    assert.deepEqual(calls.map(([, args]) => args), [
      ['ci'],
      ['ls', '--depth=0'],
    ]);
  });
});

test('npm ci retries once with the configured mirror only when no mirror is explicit', () => {
  withFixture((webappRoot) => {
    const calls = [];
    let installAttempts = 0;

    synchronizeDependencies({
      webappRoot,
      runtime: TEST_RUNTIME,
      env: {
        VANTAGE_ELECTRON_MIRROR_FALLBACK: 'https://mirror.example/electron/',
      },
      force: true,
      logger: SILENT_LOGGER,
      runCommand(command, args, options) {
        calls.push([command, args, options.env.ELECTRON_MIRROR]);
        if (args[0] === 'ci' && installAttempts++ === 0) {
          throw new Error('primary download failed');
        }
      },
    });

    assert.deepEqual(calls.map(([, args, mirror]) => [args, mirror]), [
      [['ci'], undefined],
      [['ci'], 'https://mirror.example/electron/'],
      [['ls', '--depth=0'], undefined],
    ]);
  });
});

test('an explicit Electron mirror failure is never retried with the fallback mirror', () => {
  withFixture((webappRoot) => {
    const calls = [];

    assert.throws(
      () => synchronizeDependencies({
        webappRoot,
        runtime: TEST_RUNTIME,
        env: {
          ELECTRON_MIRROR: 'https://explicit.example/electron/',
          VANTAGE_ELECTRON_MIRROR_FALLBACK: 'https://fallback.example/electron/',
        },
        force: true,
        runCommand(command, args, options) {
          calls.push([command, args, options.env.ELECTRON_MIRROR]);
          throw new Error('explicit mirror failed');
        },
      }),
      /explicit mirror failed/,
    );

    assert.deepEqual(calls.map(([, args, mirror]) => [args, mirror]), [
      [['ci'], 'https://explicit.example/electron/'],
    ]);
    assert.equal(existsSync(statePathFor(webappRoot)), false);
  });
});

test('dependency mutation invalidates the macOS native codesign stamp first', () => {
  withFixture((webappRoot) => {
    const codesignStamp = path.join(
      webappRoot,
      'node_modules',
      '.macos-native-codesign.sha256',
    );
    writeFileSync(codesignStamp, 'old-signature\n', 'utf8');

    synchronizeDependencies({
      webappRoot,
      runtime: TEST_RUNTIME,
      env: { VANTAGE_FORCE_FRONTEND_DEPS: '1' },
      invalidateStampPath: codesignStamp,
      runCommand(command, args) {
        if (args[0] === 'ci') {
          assert.equal(existsSync(codesignStamp), false);
        }
      },
    });
  });
});

test('three real processes serialize the complete dependency synchronization transaction', async () => {
  const webappRoot = createWebappFixture();
  const workerPath = writeSyncWorker(webappRoot);
  const eventsPath = path.join(webappRoot, 'events.log');
  const releasePath = path.join(webappRoot, 'release-holder');
  const signStampPath = path.join(webappRoot, 'native-sign-stamp');
  writeFileSync(signStampPath, 'stale\n', 'utf8');
  const holder = spawnSyncWorker({
    workerPath,
    webappRoot,
    workerId: 'holder',
    eventsPath,
    releasePath,
    signStampPath,
  });
  let firstFollower;
  let secondFollower;

  try {
    await waitFor(
      () => readEventLines(eventsPath).includes('holder:ci:start'),
      'the holder process never entered npm ci',
    );
    firstFollower = spawnSyncWorker({
      workerPath,
      webappRoot,
      workerId: 'first-follower',
      eventsPath,
      releasePath,
      signStampPath,
    });
    secondFollower = spawnSyncWorker({
      workerPath,
      webappRoot,
      workerId: 'second-follower',
      eventsPath,
      releasePath,
      signStampPath,
    });

    await sleep(400);
    assert.deepEqual(readEventLines(eventsPath), ['holder:ci:start']);

    writeFileSync(releasePath, 'release\n', 'utf8');
    const [holderResult, firstFollowerResult, secondFollowerResult] = await Promise.all([
      holder.completion,
      firstFollower.completion,
      secondFollower.completion,
    ]);
    assert.equal(holderResult.code, 0, holderResult.stderr);
    assert.equal(firstFollowerResult.code, 0, firstFollowerResult.stderr);
    assert.equal(secondFollowerResult.code, 0, secondFollowerResult.stderr);
    assert.deepEqual(readEventLines(eventsPath), [
      'holder:ci:start',
      'holder:ci:end',
    ]);
    assert.equal(existsSync(signStampPath), false);
    assert.equal(existsSync(statePathFor(webappRoot)), true);
  } finally {
    writeFileSync(releasePath, 'release\n', 'utf8');
    holder.child.kill('SIGKILL');
    firstFollower?.child.kill('SIGKILL');
    secondFollower?.child.kill('SIGKILL');
    await Promise.allSettled([
      holder.completion,
      ...(firstFollower ? [firstFollower.completion] : []),
      ...(secondFollower ? [secondFollower.completion] : []),
    ]);
    rmSync(webappRoot, { recursive: true, force: true });
  }
});

test('three simultaneous processes migrate one orphaned legacy lock without clobbering a new lease', async () => {
  const webappRoot = createWebappFixture();
  const workerPath = writeSyncWorker(webappRoot);
  const eventsPath = path.join(webappRoot, 'events.log');
  const releasePath = path.join(webappRoot, 'release-holder');
  const startPath = path.join(webappRoot, 'start-workers');
  const signStampPath = path.join(webappRoot, 'native-sign-stamp');
  const lockPath = dependencySyncLockPath(webappRoot);
  writeFileSync(
    lockPath,
    `${JSON.stringify({
      schemaVersion: 1,
      pid: 2147483647,
      token: 'legacy-orphan',
      createdAtMilliseconds: 1,
    })}\n`,
    { encoding: 'utf8', flag: 'wx', mode: 0o600 },
  );
  const workers = ['first', 'second', 'third'].map((workerId) => (
    spawnSyncWorker({
      workerPath,
      webappRoot,
      workerId,
      eventsPath,
      releasePath,
      startPath,
      signStampPath,
    })
  ));

  try {
    writeFileSync(startPath, 'start\n', 'utf8');
    const results = await Promise.all(workers.map((worker) => worker.completion));
    for (const result of results) {
      assert.equal(result.code, 0, result.stderr);
    }
    const events = readEventLines(eventsPath);
    assert.equal(events.filter((event) => event.endsWith(':ci:start')).length, 1);
    assert.equal(events.filter((event) => event.endsWith(':ci:end')).length, 1);
    assert.equal(lstatSync(lockPath).isDirectory(), true);
    assert.deepEqual(listDependencyLeaseNames(lockPath), []);
  } finally {
    for (const worker of workers) {
      worker.child.kill('SIGKILL');
    }
    await Promise.allSettled(workers.map((worker) => worker.completion));
    rmSync(webappRoot, { recursive: true, force: true });
  }
});

test('an identity swap makes the displaced holder fail closed before publishing state', async () => {
  const webappRoot = createWebappFixture();
  const workerPath = writeSyncWorker(webappRoot);
  const eventsPath = path.join(webappRoot, 'events.log');
  const releasePath = path.join(webappRoot, 'release-holder');
  const signStampPath = path.join(webappRoot, 'native-sign-stamp');
  const lockPath = dependencySyncLockPath(webappRoot);
  const holder = spawnSyncWorker({
    workerPath,
    webappRoot,
    workerId: 'holder',
    eventsPath,
    releasePath,
    signStampPath,
  });
  let recovery;
  let displacedLeasePath;
  let activeLeasePath;

  try {
    await waitFor(
      () => readEventLines(eventsPath).includes('holder:ci:start'),
      'the holder process never entered npm ci',
    );
    activeLeasePath = findActiveDependencyLease(lockPath);
    displacedLeasePath = `${activeLeasePath}.identity-swapped`;
    renameSync(activeLeasePath, displacedLeasePath);
    recovery = spawnSyncWorker({
      workerPath,
      webappRoot,
      workerId: 'recovery',
      eventsPath,
      releasePath,
      signStampPath,
    });
    const recoveryResult = await recovery.completion;
    assert.equal(recoveryResult.code, 0, recoveryResult.stderr);
    assert.ok(readEventLines(eventsPath).includes('recovery:ci:end'));

    writeFileSync(releasePath, 'release\n', 'utf8');
    const holderResult = await holder.completion;
    assert.equal(holderResult.code, 1, holderResult.stderr);
    assert.match(holderResult.stderr, /lock lease was lost/iu);
    assert.equal(existsSync(statePathFor(webappRoot)), true);

    rmSync(displacedLeasePath, { force: true });
  } finally {
    writeFileSync(releasePath, 'release\n', 'utf8');
    holder.child.kill('SIGKILL');
    recovery?.child.kill('SIGKILL');
    await Promise.allSettled([
      holder.completion,
      ...(recovery ? [recovery.completion] : []),
    ]);
    if (activeLeasePath) {
      rmSync(activeLeasePath, { force: true });
    }
    if (displacedLeasePath) {
      rmSync(displacedLeasePath, { force: true });
    }
    rmSync(webappRoot, { recursive: true, force: true });
  }
});

test('lease displacement in the final publish window cannot publish reusable state', () => {
  withFixture((webappRoot) => {
    const lockPath = dependencySyncLockPath(webappRoot);
    let displacedLeasePath;

    assert.throws(
      () => synchronizeDependencies({
        webappRoot,
        runtime: TEST_RUNTIME,
        env: {},
        runCommand() {},
        statePublishRaceHook() {
          const activeLeasePath = findActiveDependencyLease(lockPath);
          displacedLeasePath = `${activeLeasePath}.publish-window-swap`;
          renameSync(activeLeasePath, displacedLeasePath);
        },
      }),
      /lock lease was lost/iu,
    );
    assert.equal(existsSync(statePathFor(webappRoot)), false);

    if (displacedLeasePath) {
      rmSync(displacedLeasePath, { force: true });
    }
  });
});

test('dependency synchronization lock timeout fails closed without exposing the root path', async () => {
  const webappRoot = createWebappFixture();
  const workerPath = writeSyncWorker(webappRoot);
  const eventsPath = path.join(webappRoot, 'events.log');
  const releasePath = path.join(webappRoot, 'release-holder');
  const signStampPath = path.join(webappRoot, 'native-sign-stamp');
  const holder = spawnSyncWorker({
    workerPath,
    webappRoot,
    workerId: 'holder',
    eventsPath,
    releasePath,
    signStampPath,
  });
  let contender;

  try {
    await waitFor(
      () => readEventLines(eventsPath).includes('holder:ci:start'),
      'the holder process never entered npm ci',
    );
    contender = spawnSyncWorker({
      workerPath,
      webappRoot,
      workerId: 'contender',
      eventsPath,
      releasePath,
      signStampPath,
      lockTimeoutMilliseconds: 150,
    });
    const contenderResult = await contender.completion;

    assert.equal(contenderResult.code, 1, contenderResult.stderr);
    assert.match(
      contenderResult.stderr,
      /timed out waiting for frontend dependency synchronization lock/iu,
    );
    assert.equal(contenderResult.stderr.includes(webappRoot), false);
    assert.deepEqual(readEventLines(eventsPath), ['holder:ci:start']);
  } finally {
    writeFileSync(releasePath, 'release\n', 'utf8');
    holder.child.kill('SIGKILL');
    contender?.child.kill('SIGKILL');
    await Promise.allSettled([
      holder.completion,
      ...(contender ? [contender.completion] : []),
    ]);
    rmSync(webappRoot, { recursive: true, force: true });
  }
});

test('a crashed owner releases the lock and does not strand the next synchronizer', async () => {
  const webappRoot = createWebappFixture();
  const workerPath = writeSyncWorker(webappRoot);
  const eventsPath = path.join(webappRoot, 'events.log');
  const releasePath = path.join(webappRoot, 'release-holder');
  const signStampPath = path.join(webappRoot, 'native-sign-stamp');
  const lockPath = dependencySyncLockPath(webappRoot);
  const holder = spawnSyncWorker({
    workerPath,
    webappRoot,
    workerId: 'holder',
    eventsPath,
    releasePath,
    signStampPath,
  });
  let recovery;

  try {
    assert.equal(
      DEPENDENCY_SYNC_LOCK_FILE_NAME,
      '.vantage-frontend-dependency-sync.lock',
    );
    await waitFor(
      () => readEventLines(eventsPath).includes('holder:ci:start'),
      'the holder process never entered npm ci',
    );
    assert.equal(existsSync(lockPath), true);
    holder.child.kill('SIGKILL');
    await holder.completion;

    recovery = spawnSyncWorker({
      workerPath,
      webappRoot,
      workerId: 'recovery',
      eventsPath,
      releasePath,
      signStampPath,
      lockTimeoutMilliseconds: 3000,
    });
    const recoveryResult = await recovery.completion;
    assert.equal(recoveryResult.code, 0, recoveryResult.stderr);
    assert.equal(lstatSync(lockPath).isDirectory(), true);
    assert.deepEqual(listDependencyLeaseNames(lockPath), []);
    assert.ok(readEventLines(eventsPath).includes('recovery:ci:end'));
  } finally {
    writeFileSync(releasePath, 'release\n', 'utf8');
    holder.child.kill('SIGKILL');
    recovery?.child.kill('SIGKILL');
    await Promise.allSettled([
      holder.completion,
      ...(recovery ? [recovery.completion] : []),
    ]);
    rmSync(webappRoot, { recursive: true, force: true });
  }
});

test('a crashed owner keeps its lease until the mutating command tree stops', async () => {
  const webappRoot = createWebappFixture();
  const workerPath = writeDefaultCommandSyncWorker(webappRoot);
  const { binDirectory: fakeBinDirectory, npmPath } = writeCrashFixtureNpm(webappRoot);
  const eventsPath = path.join(webappRoot, 'crash-events.log');
  const mutatorPidPath = path.join(webappRoot, 'mutator.pid');
  const releasePath = path.join(webappRoot, 'release-crashed-command');
  const sharedEnv = {
    EVENTS_PATH: eventsPath,
    MUTATOR_PID_PATH: mutatorPidPath,
    RELEASE_PATH: releasePath,
    PATH: `${fakeBinDirectory}${path.delimiter}${process.env.PATH || ''}`,
    npm_execpath: npmPath,
    NPM_TOKEN: 'frontend-crash-secret-token',
    VANTAGE_TEST_BEARER: 'Bearer frontend-crash-secret-bearer',
  };
  const holder = spawnSyncWorker({
    workerPath,
    webappRoot,
    workerId: 'holder',
    eventsPath,
    releasePath,
    signStampPath: '',
    extraEnv: sharedEnv,
  });
  let recovery;

  try {
    await waitFor(
      () => readEventLines(eventsPath).includes('holder:ci:start')
        && existsSync(mutatorPidPath),
      'the holder command tree never started its mutator',
    );
    const holderGuardianDirectories = listCommandGuardianDirectories(webappRoot);
    assert.equal(holderGuardianDirectories.length, 1);
    const guardianContents = holderGuardianDirectories
      .map(readSurvivingGuardianFiles)
      .join('\n');
    assert.equal(guardianContents.includes(sharedEnv.NPM_TOKEN), false);
    assert.equal(guardianContents.includes(sharedEnv.VANTAGE_TEST_BEARER), false);
    const holderExit = new Promise((resolve) => {
      holder.child.once('exit', resolve);
    });
    holder.child.kill('SIGKILL');
    await holderExit;

    recovery = spawnSyncWorker({
      workerPath,
      webappRoot,
      workerId: 'recovery',
      eventsPath,
      releasePath,
      signStampPath: '',
      lockTimeoutMilliseconds: 5000,
      extraEnv: sharedEnv,
    });
    const recoveryResult = await recovery.completion;

    assert.equal(recoveryResult.code, 0, recoveryResult.stderr);
    assert.deepEqual(readEventLines(eventsPath), [
      'holder:ci:start',
      'recovery:ci:start',
      'recovery:ci:end',
    ]);
    await waitFor(
      () => listCommandGuardianDirectories(webappRoot).length === 0,
      'the command guardian left a temporary request directory behind',
    );
  } finally {
    writeFileSync(releasePath, 'release\n', 'utf8');
    holder.child.kill('SIGKILL');
    recovery?.child.kill('SIGKILL');
    await Promise.allSettled([
      holder.completion,
      ...(recovery ? [recovery.completion] : []),
    ]);
    if (existsSync(mutatorPidPath)) {
      const mutatorPid = Number(readFileSync(mutatorPidPath, 'utf8'));
      if (Number.isSafeInteger(mutatorPid)) {
        try {
          process.kill(mutatorPid, 'SIGKILL');
        } catch {
          // The crash guardian already stopped the mutator.
        }
      }
    }
    rmSync(webappRoot, { recursive: true, force: true });
  }
});

test('a successful command cannot publish state while a descendant is still alive', async () => {
  const webappRoot = createWebappFixture();
  const workerPath = writeDefaultCommandSyncWorker(webappRoot);
  const { binDirectory: fakeBinDirectory, npmPath } = writeCrashFixtureNpm(webappRoot);
  const eventsPath = path.join(webappRoot, 'success-tree-events.log');
  const mutatorPidPath = path.join(webappRoot, 'success-tree-mutator.pid');
  const releasePath = path.join(webappRoot, 'unused-release');
  const worker = spawnSyncWorker({
    workerPath,
    webappRoot,
    workerId: 'holder',
    eventsPath,
    releasePath,
    signStampPath: '',
    extraEnv: {
      EVENTS_PATH: eventsPath,
      MUTATOR_PID_PATH: mutatorPidPath,
      RELEASE_PATH: releasePath,
      PATH: `${fakeBinDirectory}${path.delimiter}${process.env.PATH || ''}`,
      npm_execpath: npmPath,
      NORMAL_EXIT_WITH_DESCENDANT: '1',
    },
  });

  try {
    const result = await worker.completion;
    assert.equal(result.code, 0, result.stderr);
    assert.equal(existsSync(statePathFor(webappRoot)), true);
    const mutatorPid = Number(readFileSync(mutatorPidPath, 'utf8'));
    assert.throws(
      () => process.kill(mutatorPid, 0),
      (error) => error?.code === 'ESRCH',
      'the dependency state was published before the descendant stopped',
    );
  } finally {
    worker.child.kill('SIGKILL');
    await Promise.allSettled([worker.completion]);
    if (existsSync(mutatorPidPath)) {
      const mutatorPid = Number(readFileSync(mutatorPidPath, 'utf8'));
      if (Number.isSafeInteger(mutatorPid)) {
        try {
          process.kill(mutatorPid, 'SIGKILL');
        } catch {
          // The command guardian already stopped the descendant.
        }
        await waitFor(
          () => {
            try {
              process.kill(mutatorPid, 0);
              return false;
            } catch {
              return true;
            }
          },
          'the descendant did not stop during test cleanup',
        );
      }
    }
    await removeFixtureWhenIdle(webappRoot);
  }
});

test('an orphaned lock file is reclaimed instead of blocking synchronization', () => {
  withFixture((webappRoot) => {
    const lockPath = dependencySyncLockPath(webappRoot);
    writeFileSync(
      lockPath,
      `${JSON.stringify({
        schemaVersion: 1,
        pid: 2147483647,
        token: 'orphaned-owner',
        createdAtMilliseconds: 1,
      })}\n`,
      { encoding: 'utf8', flag: 'wx', mode: 0o600 },
    );

    const result = synchronizeDependencies({
      webappRoot,
      runtime: TEST_RUNTIME,
      env: {},
      lockTimeoutMilliseconds: 500,
      runCommand() {},
    });

    assert.equal(result.synchronized, true);
    assert.equal(lstatSync(lockPath).isDirectory(), true);
    assert.deepEqual(listDependencyLeaseNames(lockPath), []);
  });
});

test('orphaned choosing and ticket leases are removed by their unique paths', () => {
  withFixture((webappRoot) => {
    const lockPath = dependencySyncLockPath(webappRoot);
    mkdirSync(lockPath, { mode: 0o700 });
    const staleToken = '0123456789abcdef0123456789abcdef';
    const staleOwner = `${JSON.stringify({
      schemaVersion: 2,
      pid: 2147483647,
      token: staleToken,
      createdAtMilliseconds: 1,
    })}\n`;
    writeFileSync(
      path.join(lockPath, `choosing-2147483647-${staleToken}.json`),
      staleOwner,
      { encoding: 'utf8', flag: 'wx', mode: 0o600 },
    );
    writeFileSync(
      path.join(
        lockPath,
        `ticket-0000000000000001-2147483647-${staleToken}.json`,
      ),
      staleOwner,
      { encoding: 'utf8', flag: 'wx', mode: 0o600 },
    );

    const result = synchronizeDependencies({
      webappRoot,
      runtime: TEST_RUNTIME,
      env: {},
      lockTimeoutMilliseconds: 500,
      runCommand() {},
    });

    assert.equal(result.synchronized, true);
    assert.deepEqual(listDependencyLeaseNames(lockPath), []);
  });
});

test('a linked lock path fails closed without touching the link target', (context) => {
  const webappRoot = createWebappFixture();
  const externalRoot = mkdtempSync(path.join(tmpdir(), 'vantage-lock-target-'));
  const lockPath = dependencySyncLockPath(webappRoot);
  const externalFile = path.join(externalRoot, 'owner.json');
  const externalContents = '{"external":true}\n';
  writeFileSync(externalFile, externalContents, 'utf8');

  try {
    try {
      linkSync(externalFile, lockPath);
    } catch (error) {
      context.skip(`hard-link creation unavailable: ${error.code}`);
      return;
    }
    assert.throws(
      () => synchronizeDependencies({
        webappRoot,
        runtime: TEST_RUNTIME,
        env: {},
        lockTimeoutMilliseconds: 100,
        runCommand() {},
      }),
      /lock is unsafe/iu,
    );
    assert.equal(readFileSync(externalFile, 'utf8'), externalContents);
  } finally {
    rmSync(webappRoot, { recursive: true, force: true });
    rmSync(externalRoot, { recursive: true, force: true });
  }
});

test('a lock-directory junction fails closed without writing through it', (context) => {
  const webappRoot = createWebappFixture();
  const externalRoot = mkdtempSync(path.join(tmpdir(), 'vantage-lock-dir-'));
  const lockPath = dependencySyncLockPath(webappRoot);

  try {
    try {
      symlinkSync(
        externalRoot,
        lockPath,
        process.platform === 'win32' ? 'junction' : 'dir',
      );
    } catch (error) {
      context.skip(`directory-link creation unavailable: ${error.code}`);
      return;
    }
    assert.throws(
      () => synchronizeDependencies({
        webappRoot,
        runtime: TEST_RUNTIME,
        env: {},
        lockTimeoutMilliseconds: 100,
        runCommand() {},
      }),
      /lock is unsafe/iu,
    );
    assert.deepEqual(readdirSync(externalRoot), []);
  } finally {
    rmSync(webappRoot, { recursive: true, force: true });
    rmSync(externalRoot, { recursive: true, force: true });
  }
});

test('transient dependency lock artifacts cannot dirty the public worktree', () => {
  const webappRoot = fileURLToPath(new URL('..', import.meta.url));
  const ignoreRules = readFileSync(path.join(webappRoot, '.gitignore'), 'utf8')
    .split(/\r?\n/u);

  assert.ok(ignoreRules.includes(`${DEPENDENCY_SYNC_LOCK_FILE_NAME}*`));
});

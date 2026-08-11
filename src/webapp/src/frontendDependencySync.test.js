import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const {
  STATE_FILE_NAME,
  buildDesiredState,
  resolveNpmExecution,
  scanInstalledPackages,
  synchronizeDependencies,
  writeStateAtomically,
} = require('../scripts/sync-dependencies.cjs');

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

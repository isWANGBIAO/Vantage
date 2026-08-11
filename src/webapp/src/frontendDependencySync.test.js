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
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const {
  STATE_FILE_NAME,
  buildDesiredState,
  resolveNpmExecution,
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

function writeDesiredState(webappRoot, runtime = TEST_RUNTIME) {
  const state = buildDesiredState({ webappRoot, runtime });
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
      buildDesiredState({ webappRoot, runtime: TEST_RUNTIME }),
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

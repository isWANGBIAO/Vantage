// Compile and inspect disposable Windows artifacts; never launch or install them.
// The backend is deliberately synthetic: this is not real-backend acceptance.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { spawn } = require('node:child_process');

const WEBAPP_ROOT = path.resolve(__dirname, '..');
const TEMP_PREFIX = 'vantage-dependency-package-';
const OWNER_FILE = '.smoke-owner';
const BACKEND_DESTINATION = 'backend-runtime/VantageBackend';
const FIXTURE_FILE = 'SYNTHETIC_BACKEND_FIXTURE.txt';

function assertWindows(platform = process.platform) {
  assert.equal(platform, 'win32', 'Dependency packaging smoke requires Windows');
}

function createBuildEnvironment(source = process.env, ownedRoot) {
  const env = { ...source };
  for (const key of Object.keys(env)) {
    if (/^(?:WIN_)?CSC_/i.test(key)) delete env[key];
  }
  env.CSC_IDENTITY_AUTO_DISCOVERY = 'false';
  if (ownedRoot) {
    const cache = path.join(ownedRoot, 'cache');
    env.ELECTRON_BUILDER_CACHE = path.join(cache, 'builder');
    env.ELECTRON_CACHE = path.join(cache, 'electron');
    env.electron_config_cache = env.ELECTRON_CACHE;
    env.npm_config_cache = path.join(cache, 'npm');
    env.XDG_CACHE_HOME = cache;
    env.TEMP = path.join(ownedRoot, 'tmp');
    env.TMP = env.TEMP;
    env.TMPDIR = env.TEMP;
  }
  return env;
}

function createSmokeConfig(production, output, fixture) {
  const config = structuredClone(production);
  const backends = config.extraResources.filter((resource) => resource.to === BACKEND_DESTINATION);
  assert.equal(backends.length, 1, 'Expected one configured backend resource');
  config.extraResources = config.extraResources.map((resource) => (
    resource.to === BACKEND_DESTINATION ? { ...resource, from: fixture } : resource
  ));
  config.directories = { ...config.directories, output };
  // Keep resource editing (including the V icon), but never sign this fixture.
  config.win = { ...config.win, signExecutable: false };
  config.forceCodeSigning = false;
  return config;
}

function createBuildOptions(configFile) {
  // An object here is merged into package.build (including file-set arrays).
  // An explicit complete config file avoids accidentally retaining the real backend.
  return { projectDir: WEBAPP_ROOT, config: configFile, publish: 'never' };
}

function assertOwnedTemporaryRoot(root, owner) {
  const absolute = path.resolve(root);
  const temporary = fs.realpathSync(os.tmpdir());
  const valid = path.dirname(absolute) === temporary
    && path.basename(absolute).startsWith(TEMP_PREFIX)
    && fs.existsSync(absolute)
    && !fs.lstatSync(absolute).isSymbolicLink()
    && fs.realpathSync(absolute) === absolute
    && fs.existsSync(path.join(absolute, OWNER_FILE))
    && fs.readFileSync(path.join(absolute, OWNER_FILE), 'utf8') === owner;
  assert.ok(valid, 'Refusing access outside the owned temporary packaging directory');
  return absolute;
}

function removeOwnedTemporaryRoot(root, owner) {
  fs.rmSync(assertOwnedTemporaryRoot(root, owner), { recursive: true, force: true });
}

function assertNonemptyFile(file) {
  assert.ok(fs.statSync(file).isFile() && fs.statSync(file).size > 0, `Missing or empty artifact: ${path.basename(file)}`);
}

function verifyUnpacked(output) {
  const asar = require('@electron/asar');
  const unpacked = path.join(output, 'win-unpacked');
  assertNonemptyFile(path.join(unpacked, 'Vantage.exe'));
  const archive = path.join(unpacked, 'resources', 'app.asar');
  assertNonemptyFile(archive);
  const entries = asar.listPackage(archive).map((entry) => entry.replace(/\\/g, '/').replace(/^\//, ''));
  for (const file of ['main.cjs', 'preload.cjs', 'dist/index.html', 'assets/icon.ico', 'never-stop/core/runner.cjs', 'node_modules/ssh2/package.json']) {
    assert.ok(entries.includes(file), `Missing production archive entry: ${file}`);
  }
  for (const name of ['roarr', 'sprintf-js', 'global-agent', 'electron-builder', 'app-builder-lib']) {
    assert.ok(!entries.some((entry) => entry.includes(`node_modules/${name}/`)), `Build-only dependency leaked into app.asar: ${name}`);
  }
  for (const file of ['main.cjs', 'preload.cjs', 'dist/index.html', 'assets/icon.ico']) {
    assert.deepEqual(asar.extractFile(archive, file), fs.readFileSync(path.join(WEBAPP_ROOT, file)), `Archive differs from production source: ${file}`);
  }
  for (const file of ['vantage.cmd', 'vantage-cli-path.ps1']) {
    assert.deepEqual(
      fs.readFileSync(path.join(unpacked, 'resources', 'cli-bin', file)),
      fs.readFileSync(path.join(WEBAPP_ROOT, 'cli', file)),
      `Real CLI resource differs: ${file}`,
    );
  }
  assertNonemptyFile(path.join(unpacked, 'resources', BACKEND_DESTINATION, FIXTURE_FILE));
  assert.ok(!fs.existsSync(path.join(unpacked, 'resources', BACKEND_DESTINATION, 'VantageBackend.exe')));
  return unpacked;
}

async function runBuilder(payloadFile) {
  assertWindows();
  const payload = JSON.parse(fs.readFileSync(payloadFile, 'utf8'));
  const root = assertOwnedTemporaryRoot(path.dirname(payloadFile), payload.owner);
  // Set only after ownership validation against the original system temp root.
  // This process is the disposable worker, never the invoking shell/application.
  Object.assign(process.env, createBuildEnvironment(process.env, root));
  fs.mkdirSync(process.env.TEMP, { recursive: true });
  const { build, Platform, Arch } = require('electron-builder');
  assert.equal(require('electron-builder/package.json').version, '26.15.3');
  assert.equal(require('electron/package.json').version, '42.11.14');
  const configFile = path.join(root, 'builder-config.json');
  fs.writeFileSync(configFile, JSON.stringify(payload.config));
  const options = createBuildOptions(configFile);
  await build({ ...options, targets: Platform.WINDOWS.createTarget('dir', Arch.x64) });
  const unpacked = verifyUnpacked(payload.config.directories.output);
  const artifacts = await build({
    ...options,
    prepackaged: unpacked,
    targets: Platform.WINDOWS.createTarget('nsis', Arch.x64),
  });
  const installers = artifacts.filter((file) => /\.exe$/i.test(file));
  assert.equal(installers.length, 1, 'Expected one NSIS executable');
  const installer = installers[0];
  const output = path.resolve(payload.config.directories.output);
  assert.ok(path.resolve(installer).startsWith(`${output}${path.sep}`), 'Installer escaped temporary output');
  assertNonemptyFile(installer);
  const fd = fs.openSync(installer, 'r');
  try {
    const header = Buffer.alloc(2);
    assert.equal(fs.readSync(fd, header, 0, 2, 0), 2);
    assert.equal(header.toString('ascii'), 'MZ', 'NSIS artifact is not a Windows executable');
  } finally {
    fs.closeSync(fd);
  }
  console.log(JSON.stringify({
    scope: 'synthetic-backend Windows unpacked and NSIS compilation only; no launch or installation',
    builder: '26.15.3', electron: '42.11.14',
    productionEntriesAndCliVerified: true,
    buildOnlyDependenciesExcluded: true,
    installerBytes: fs.statSync(installer).size,
  }));
}

async function main() {
  assertWindows();
  assert.equal(process.argv.length, 2, 'This smoke script accepts no public arguments');
  for (const file of ['dist/index.html', 'main.cjs', 'preload.cjs', 'assets/icon.ico', 'build/installer.nsh', 'cli/vantage.cmd', 'cli/vantage-cli-path.ps1']) {
    assertNonemptyFile(path.join(WEBAPP_ROOT, file));
  }
  const metadata = JSON.parse(fs.readFileSync(path.join(WEBAPP_ROOT, 'package.json'), 'utf8'));
  const root = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), TEMP_PREFIX));
  const owner = randomUUID();
  fs.writeFileSync(path.join(root, OWNER_FILE), owner, { flag: 'wx' });
  try {
    const fixture = path.join(root, 'synthetic-backend');
    fs.mkdirSync(fixture);
    fs.writeFileSync(path.join(fixture, FIXTURE_FILE), 'SYNTHETIC TEST FIXTURE ONLY. Not an executable backend. Never install or launch this package.\n');
    const config = createSmokeConfig(metadata.build, path.join(root, 'output'), fixture);
    const payloadFile = path.join(root, 'smoke-config.json');
    fs.writeFileSync(payloadFile, JSON.stringify({ owner, config }));
    await new Promise((resolve, reject) => {
      const child = spawn(process.execPath, [__filename, '--worker', payloadFile], {
        cwd: WEBAPP_ROOT,
        env: createBuildEnvironment(),
        stdio: 'inherit',
        windowsHide: true,
      });
      child.once('error', reject);
      child.once('exit', (code, signal) => {
        if (code === 0) resolve();
        else reject(new Error(`Packaging worker failed (exit ${code}, signal ${signal || 'none'})`));
      });
    });
  } finally {
    removeOwnedTemporaryRoot(root, owner);
  }
  console.log('Temporary packaging artifacts removed; no application or installer was launched.');
}

module.exports = { assertWindows, createBuildEnvironment, createSmokeConfig, createBuildOptions, removeOwnedTemporaryRoot };

if (require.main === module) {
  const operation = process.argv[2] === '--worker' && process.argv.length === 4
    ? () => runBuilder(process.argv[3]) : main;
  operation().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}

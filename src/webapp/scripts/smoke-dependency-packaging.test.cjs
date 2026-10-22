const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const smoke = require('./smoke-dependency-packaging.cjs');

test('smoke configuration preserves production identity, resources and NSIS inputs', () => {
  assert.equal(typeof smoke.createSmokeConfig, 'function');
  const source = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json')));
  const original = structuredClone(source.build);
  const config = smoke.createSmokeConfig(source.build, '/temporary/output', '/temporary/fixture');
  assert.deepEqual(source.build, original);
  assert.equal(config.appId, original.appId);
  assert.equal(config.productName, original.productName);
  assert.equal(config.win.icon, original.win.icon);
  assert.deepEqual(config.files, original.files);
  assert.deepEqual(config.win.extraResources, original.win.extraResources);
  assert.deepEqual(config.nsis, original.nsis);
  assert.deepEqual(config.extraResources, [{
    ...original.extraResources[0], from: '/temporary/fixture',
  }]);
  assert.equal(config.directories.output, '/temporary/output');
  assert.equal(config.win.signExecutable, false);
});

test('builder loads the complete fixture config file instead of merging package resource arrays', () => {
  assert.equal(typeof smoke.createBuildOptions, 'function');
  const file = path.join(os.tmpdir(), 'fixture-builder-config.json');
  const options = smoke.createBuildOptions(file);
  assert.equal(options.config, file);
  assert.equal(options.publish, 'never');
  assert.equal(options.projectDir, path.resolve(__dirname, '..'));
});

test('child environment removes signing credentials without modifying the caller', () => {
  assert.equal(typeof smoke.createBuildEnvironment, 'function');
  const source = {
    PATH: 'retained', CSC_LINK: 'secret', WIN_CSC_LINK: 'secret',
    CSC_KEY_PASSWORD: 'secret', WIN_CSC_KEY_PASSWORD: 'secret',
    CSC_IDENTITY_AUTO_DISCOVERY: 'true',
  };
  const actual = smoke.createBuildEnvironment(source);
  assert.equal(actual.PATH, 'retained');
  assert.equal(actual.CSC_IDENTITY_AUTO_DISCOVERY, 'false');
  for (const key of ['CSC_LINK', 'WIN_CSC_LINK', 'CSC_KEY_PASSWORD', 'WIN_CSC_KEY_PASSWORD']) {
    assert.equal(Object.hasOwn(actual, key), false);
    assert.equal(source[key], 'secret');
  }
});

test('worker cache and temporary paths stay below its owned directory, not user caches', () => {
  const root = path.join(os.tmpdir(), 'vantage-dependency-package-test-owner');
  const source = { TEMP: 'parent-temp', ELECTRON_BUILDER_CACHE: 'parent-cache' };
  const actual = smoke.createBuildEnvironment(source, root);
  for (const key of ['ELECTRON_BUILDER_CACHE', 'ELECTRON_CACHE', 'electron_config_cache', 'npm_config_cache', 'XDG_CACHE_HOME', 'TEMP', 'TMP', 'TMPDIR']) {
    assert.ok(actual[key]?.startsWith(`${root}${path.sep}`), `${key} must stay inside the owned root`);
  }
  assert.deepEqual(source, { TEMP: 'parent-temp', ELECTRON_BUILDER_CACHE: 'parent-cache' });
});

test('temporary cleanup rejects arbitrary directories, sibling prefixes and foreign ownership', () => {
  assert.equal(typeof smoke.removeOwnedTemporaryRoot, 'function');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-dependency-package-'));
  try {
    fs.writeFileSync(path.join(root, '.smoke-owner'), 'owner');
    assert.throws(() => smoke.removeOwnedTemporaryRoot(os.tmpdir(), 'owner'), /owned temporary/);
    assert.throws(() => smoke.removeOwnedTemporaryRoot(`${root}-sibling`, 'owner'), /owned temporary/);
    assert.throws(() => smoke.removeOwnedTemporaryRoot(root, 'foreign'), /owned temporary/);
    assert.equal(fs.existsSync(root), true);
    smoke.removeOwnedTemporaryRoot(root, 'owner');
    assert.equal(fs.existsSync(root), false);
  } finally {
    if (fs.existsSync(root)) fs.rmSync(root, { recursive: true, force: true });
  }
});

test('platform guard rejects unsupported hosts before loading builder or creating artifacts', () => {
  assert.equal(typeof smoke.assertWindows, 'function');
  assert.throws(() => smoke.assertWindows('linux'), /requires Windows/);
  assert.doesNotThrow(() => smoke.assertWindows('win32'));
});

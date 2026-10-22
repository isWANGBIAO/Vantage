const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { inputFingerprint, recordBuild, isBuildCurrent, STATE_NAME } = require('./frontendBuildCache.cjs');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-build-cache-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  for (const [name, content] of Object.entries({
    'src/main.js': 'original source', 'package-lock.json': '{"version":1}',
    'dist/index.html': '<script src="./assets/main.js"></script>',
    'dist/assets/main.js': 'original output', 'dist/assets/main.css': 'body {}',
  })) {
    fs.mkdirSync(path.dirname(path.join(root, name)), { recursive: true });
    fs.writeFileSync(path.join(root, name), content);
  }
  recordBuild(root, inputFingerprint(root));
  assert.equal(isBuildCurrent(root), true);
  return root;
}

for (const output of ['index.html', 'assets/main.js', 'assets/main.css']) {
  for (const change of ['delete', 'truncate']) {
    test(`${change} ${output} invalidates cache`, (t) => {
      const root = fixture(t);
      const file = path.join(root, 'dist', output);
      if (change === 'delete') fs.unlinkSync(file);
      else fs.writeFileSync(file, '');
      assert.equal(isBuildCurrent(root), false);
    });
  }
}

test('content changes invalidate cache even when source mtime is restored', (t) => {
  const root = fixture(t);
  const file = path.join(root, 'src/main.js');
  const before = fs.statSync(file);
  fs.writeFileSync(file, 'changed source');
  fs.utimesSync(file, before.atime, before.mtime);
  assert.equal(isBuildCurrent(root), false);
});

test('lockfile changes and source removal invalidate cache', (t) => {
  const root = fixture(t);
  fs.writeFileSync(path.join(root, 'package-lock.json'), '{"version":2}');
  assert.equal(isBuildCurrent(root), false);
  recordBuild(root, inputFingerprint(root));
  fs.unlinkSync(path.join(root, 'src/main.js'));
  assert.equal(isBuildCurrent(root), false);
});

test('missing or corrupt state requires rebuild', (t) => {
  const root = fixture(t);
  const state = path.join(root, 'dist', STATE_NAME);
  fs.writeFileSync(state, '{');
  assert.equal(isBuildCurrent(root), false);
  fs.unlinkSync(state);
  assert.equal(isBuildCurrent(root), false);
});

test('build cannot certify inputs that changed while it was running', (t) => {
  const root = fixture(t);
  const inputs = inputFingerprint(root);
  fs.writeFileSync(path.join(root, 'src/main.js'), 'new input');
  assert.throws(() => recordBuild(root, inputs), /inputs changed/);
  assert.equal(isBuildCurrent(root), false);
});

test('build wrapper publishes cache only after success and checker rejects deleted output', (t) => {
  const { spawnSync } = require('node:child_process');
  const root = fixture(t);
  const webapp = path.resolve(__dirname, '../..');
  for (const relative of ['scripts/vite-build.mjs', 'check_build.js', 'src/utils/frontendBuildCache.cjs']) {
    const target = path.join(root, relative);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.copyFileSync(path.join(webapp, relative), target);
  }
  fs.writeFileSync(path.join(root, 'package.json'), '{"type":"module"}');
  const vite = path.join(root, 'node_modules/vite/bin/vite.js');
  fs.mkdirSync(path.dirname(vite), { recursive: true });
  fs.writeFileSync(vite, '');
  const run = (file) => spawnSync(process.execPath, [path.join(root, file)], { encoding: 'utf8' });
  assert.equal(run('scripts/vite-build.mjs').status, 0);
  assert.equal(run('check_build.js').status, 0);
  fs.unlinkSync(path.join(root, 'dist/assets/main.js'));
  assert.equal(run('check_build.js').status, 1);
  fs.writeFileSync(vite, 'process.exit(7);');
  assert.equal(run('scripts/vite-build.mjs').status, 7);
  assert.equal(fs.existsSync(path.join(root, 'dist', STATE_NAME)), false);
  assert.equal(run('check_build.js').status, 1);
});

for (const location of ['src', 'dist']) {
  test(`${location} symbolic links cannot escape or recurse during cache validation`, (t) => {
    const root = fixture(t);
    const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-external-fixture-'));
    t.after(() => fs.rmSync(outside, { recursive: true, force: true }));
    fs.writeFileSync(path.join(outside, 'synthetic.txt'), 'must not be hashed');
    const link = path.join(root, location, 'link');
    fs.symlinkSync(outside, link, process.platform === 'win32' ? 'junction' : 'dir');
    assert.equal(isBuildCurrent(root), false);
    if (location === 'src') assert.throws(() => inputFingerprint(root), /symbolic links/);
    else assert.throws(() => recordBuild(root, inputFingerprint(root)), /symbolic links/);
    fs.unlinkSync(link);
    fs.symlinkSync(path.join(root, location), link, process.platform === 'win32' ? 'junction' : 'dir');
    assert.equal(isBuildCurrent(root), false);
  });
}

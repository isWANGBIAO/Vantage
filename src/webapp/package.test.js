import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const packageJson = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'));
const preloadSource = readFileSync(new URL('./preload.cjs', import.meta.url), 'utf8');

test('package exposes frontend test and check scripts', () => {
  assert.ok(packageJson.scripts.test);
  assert.ok(packageJson.scripts.check);
  assert.ok(packageJson.scripts['electron:package']);
  assert.match(packageJson.scripts.test, /node --test/);
  assert.match(packageJson.scripts.check, /npm run test/);
  assert.equal(packageJson.scripts['electron:package'], 'electron-builder');
});

test('package bundles the backend runtime and installer shortcuts for Windows', () => {
  assert.ok(packageJson.build.files.includes('src/utils/**/*.cjs'));
  assert.deepEqual(packageJson.build.win.target, ['nsis']);
  assert.ok(Array.isArray(packageJson.build.extraResources));
  assert.ok(
    packageJson.build.extraResources.some(
      (entry) =>
        entry.from === '../../build/backend-runtime/stage/VantageBackend'
        && entry.to === 'backend-runtime/VantageBackend',
    ),
  );
  assert.equal(packageJson.build.nsis.oneClick, false);
  assert.equal(packageJson.build.nsis.allowToChangeInstallationDirectory, true);
  assert.equal(packageJson.build.nsis.createDesktopShortcut, 'always');
  assert.equal(packageJson.build.nsis.createStartMenuShortcut, true);
  assert.equal(packageJson.build.nsis.shortcutName, 'Vantage');
  assert.equal(packageJson.build.nsis.deleteAppDataOnUninstall, false);
  assert.equal(packageJson.build.nsis.warningsAsErrors, false);
  assert.deepEqual(packageJson.build.nsis.customNsisBinary, {
    url: 'https://github.com/SoundSafari/NSISBI-ElectronBuilder/releases/download/1.0.0/nsisbi-electronbuilder-3.10.3.7z',
    checksum: 'WRmZUsACjIc2s7bvsFGFRofK31hfS7riPlcfI1V9uFB2Q8s7tidgI/9U16+X0I9X2ZhNxi8N7Z3gKvm6ojvLvg==',
  });
});

test('preload does not emit startup console noise', () => {
  assert.equal(preloadSource.includes("console.log('Electron preload script loaded')"), false);
});

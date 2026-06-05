import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import process from 'node:process';

const packageJson = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'));
const preloadSource = readFileSync(new URL('./preload.cjs', import.meta.url), 'utf8');
const signMacAdHocSource = readFileSync(new URL('./scripts/sign-mac-ad-hoc.cjs', import.meta.url), 'utf8');
const viteBuildScriptSource = readFileSync(new URL('./scripts/vite-build.mjs', import.meta.url), 'utf8');
const runBatSource = readFileSync(new URL('../../RUN.bat', import.meta.url), 'utf8');

test('package exposes frontend test and check scripts', () => {
  assert.ok(packageJson.scripts.test);
  assert.ok(packageJson.scripts.check);
  assert.ok(packageJson.scripts['electron:package']);
  assert.match(packageJson.scripts.test, /node --test/);
  assert.equal(packageJson.scripts.build, 'node scripts/vite-build.mjs');
  assert.match(packageJson.scripts.check, /npm run test/);
  assert.equal(packageJson.scripts['electron:package'], 'electron-builder');
});

test('build script normalizes junction paths before invoking Vite', () => {
  assert.ok(existsSync(new URL('./scripts/vite-build.mjs', import.meta.url)));
  assert.ok(viteBuildScriptSource.includes('realpathSync'));
  assert.ok(viteBuildScriptSource.includes("path.join("));
  assert.ok(viteBuildScriptSource.includes("'vite.js'"));
  assert.ok(viteBuildScriptSource.includes("[viteCli, 'build', webappRoot]"));
});

test('package bundles the backend runtime and installer shortcuts for Windows', () => {
  assert.ok(packageJson.build.files.includes('src/utils/**/*.cjs'));
  assert.equal(packageJson.build.afterPack, './scripts/sign-mac-ad-hoc.cjs');
  assert.deepEqual(packageJson.build.win.target, ['nsis']);
  assert.deepEqual(packageJson.build.mac.target, ['dmg', 'zip']);
  assert.equal(packageJson.build.mac.category, 'public.app-category.healthcare-fitness');
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

test('preload can prime renderer camera access for macOS permission prompts', () => {
  assert.ok(preloadSource.includes("ipcRenderer.on('camera:prime-renderer-access'"));
  assert.ok(preloadSource.includes("navigator.mediaDevices.getUserMedia({ video: true, audio: false })"));
  assert.ok(preloadSource.includes("ipcRenderer.send('camera:renderer-access-result'"));
  assert.ok(preloadSource.includes('track.stop()'));
});

test('preload can bridge renderer camera frames to the main process', () => {
  assert.ok(preloadSource.includes("CAMERA_FRAME_BRIDGE_START_CHANNEL = 'camera:start-frame-bridge'"));
  assert.ok(preloadSource.includes("CAMERA_FRAME_CHANNEL = 'camera:renderer-frame'"));
  assert.ok(preloadSource.includes("navigator.mediaDevices.getUserMedia({"));
  assert.ok(preloadSource.includes('playVideoWithTimeout'));
  assert.ok(preloadSource.includes("renderer camera video play timed out"));
  assert.ok(preloadSource.includes('(document.body || document.documentElement)?.appendChild(video)'));
  assert.ok(preloadSource.includes("canvas.toBlob(resolve, 'image/jpeg', quality)"));
  assert.ok(preloadSource.includes('Buffer.from(arrayBuffer)'));
  assert.ok(preloadSource.includes('ipcRenderer.send(CAMERA_FRAME_CHANNEL, buffer)'));
  assert.ok(preloadSource.includes('camera:frame-bridge-result'));
});

test('macOS packaging hook ad-hoc signs the finished app bundle from a temp copy', () => {
  assert.equal(packageJson.build.afterPack, './scripts/sign-mac-ad-hoc.cjs');
  assert.ok(signMacAdHocSource.includes("context?.electronPlatformName !== 'darwin'"));
  assert.ok(signMacAdHocSource.includes('walkAsync'));
  assert.ok(signMacAdHocSource.includes('isMachOFile'));
  assert.ok(signMacAdHocSource.includes('function commandPath'));
  assert.ok(signMacAdHocSource.includes('path.relative(process.cwd(), filePath)'));
  assert.ok(signMacAdHocSource.includes("fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-mac-sign-'))"));
  assert.ok(signMacAdHocSource.includes("run('ditto', [outputAppPath, appPath])"));
  assert.ok(signMacAdHocSource.includes("run('ditto', [appPath, outputAppPath])"));
  assert.ok(signMacAdHocSource.includes('codesignPath'));
  assert.ok(signMacAdHocSource.includes('codesignPathWithShell'));
  assert.ok(signMacAdHocSource.includes('codesignTopLevelApp'));
  assert.ok(signMacAdHocSource.includes('AD_HOC_MAIN_ENTITLEMENTS'));
  assert.ok(signMacAdHocSource.includes('clearSignBlockingAttributesRecursive'));
  assert.ok(signMacAdHocSource.includes("path.basename(filePath) === 'VantageBackend'"));
  assert.ok(signMacAdHocSource.includes('com.apple.security.cs.disable-library-validation'));
  assert.ok(signMacAdHocSource.includes("run('xattr', ['-cr', bundlePath]"));
  assert.ok(signMacAdHocSource.includes('com.apple.FinderInfo'));
  assert.ok(signMacAdHocSource.includes('com.apple.fileprovider.fpfs#P'));
  assert.ok(signMacAdHocSource.includes("'--strict'"));
});

test('build version script bumps patch and writes build metadata', async () => {
  const root = mkdtempSync(path.join(tmpdir(), 'vantage-version-'));
  const packagePath = path.join(root, 'package.json');
  const lockPath = path.join(root, 'package-lock.json');
  const buildInfoPath = path.join(root, 'build-info.json');
  writeFileSync(packagePath, JSON.stringify({ name: 'vantage', version: '1.0.0' }, null, 2), 'utf8');
  writeFileSync(
    lockPath,
    JSON.stringify({
      name: 'vantage',
      version: '1.0.0',
      packages: {
        '': {
          name: 'vantage',
          version: '1.0.0',
        },
      },
    }, null, 2),
    'utf8',
  );

  const { prepareBuildVersion } = await import('./scripts/prepare-build-version.mjs');
  const result = prepareBuildVersion({
    webappRoot: root,
    now: new Date('2026-05-03T12:00:00+08:00'),
    commit: 'abcdef1',
  });

  assert.equal(result.version, '1.0.1');
  assert.equal(JSON.parse(readFileSync(packagePath, 'utf8')).version, '1.0.1');
  assert.equal(JSON.parse(readFileSync(lockPath, 'utf8')).version, '1.0.1');
  assert.equal(JSON.parse(readFileSync(lockPath, 'utf8')).packages[''].version, '1.0.1');
  assert.deepEqual(JSON.parse(readFileSync(buildInfoPath, 'utf8')), {
    version: '1.0.1',
    build_date: '2026-05-03T04:00:00.000Z',
    build_commit: 'abcdef1',
  });
  assert.equal(result.bumped, true);
});

test('build version script runs from the CLI on Windows-style relative paths', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'vantage-version-cli-'));
  const packagePath = path.join(root, 'package.json');
  const buildInfoPath = path.join(root, 'build-info.json');
  writeFileSync(packagePath, JSON.stringify({ name: 'vantage', version: '2.3.4' }, null, 2), 'utf8');
  const scriptPath = process.platform === 'win32'
    ? 'scripts\\prepare-build-version.mjs'
    : 'scripts/prepare-build-version.mjs';

  const output = execFileSync(
    process.execPath,
    [scriptPath, '--webapp-root', root],
    { cwd: new URL('.', import.meta.url), encoding: 'utf8' },
  );

  assert.match(output, /Prepared Vantage build 2\.3\.5/);
  assert.equal(JSON.parse(readFileSync(packagePath, 'utf8')).version, '2.3.5');
  assert.equal(JSON.parse(readFileSync(buildInfoPath, 'utf8')).version, '2.3.5');
});

test('build version script auto mode keeps committed versions unchanged on a clean tree', async () => {
  const root = mkdtempSync(path.join(tmpdir(), 'vantage-version-auto-clean-'));
  const packagePath = path.join(root, 'package.json');
  const lockPath = path.join(root, 'package-lock.json');
  const buildInfoPath = path.join(root, 'build-info.json');
  const packagePayload = { name: 'vantage', version: '3.4.5' };
  const buildInfoPayload = {
    version: '3.4.5',
    build_date: '2026-05-03T04:00:00.000Z',
    build_commit: 'clean123',
  };
  writeFileSync(packagePath, JSON.stringify(packagePayload, null, 2), 'utf8');
  writeFileSync(lockPath, JSON.stringify({ name: 'vantage', version: '3.4.5', packages: { '': packagePayload } }, null, 2), 'utf8');
  writeFileSync(buildInfoPath, JSON.stringify(buildInfoPayload, null, 2), 'utf8');

  const { prepareBuildVersion } = await import('./scripts/prepare-build-version.mjs');
  const result = prepareBuildVersion({
    webappRoot: root,
    mode: 'auto',
    commit: 'ignored999',
    gitClean: true,
  });

  assert.equal(result.bumped, false);
  assert.equal(result.version, '3.4.5');
  assert.equal(JSON.parse(readFileSync(packagePath, 'utf8')).version, '3.4.5');
  assert.equal(JSON.parse(readFileSync(lockPath, 'utf8')).version, '3.4.5');
  assert.deepEqual(JSON.parse(readFileSync(buildInfoPath, 'utf8')), buildInfoPayload);
});

test('build version script auto mode bumps when tracked changes are present', async () => {
  const root = mkdtempSync(path.join(tmpdir(), 'vantage-version-auto-dirty-'));
  const packagePath = path.join(root, 'package.json');
  const buildInfoPath = path.join(root, 'build-info.json');
  writeFileSync(packagePath, JSON.stringify({ name: 'vantage', version: '4.0.0' }, null, 2), 'utf8');

  const { prepareBuildVersion } = await import('./scripts/prepare-build-version.mjs');
  const result = prepareBuildVersion({
    webappRoot: root,
    mode: 'auto',
    now: new Date('2026-05-03T12:00:00+08:00'),
    commit: 'dirty123',
    gitClean: false,
  });

  assert.equal(result.bumped, true);
  assert.equal(JSON.parse(readFileSync(packagePath, 'utf8')).version, '4.0.1');
  assert.equal(JSON.parse(readFileSync(buildInfoPath, 'utf8')).version, '4.0.1');
});

test('RUN.bat prepares build version in auto mode but does not commit automatically', () => {
  assert.ok(runBatSource.includes('prepare-build-version.mjs --mode auto'));
  assert.equal(/git\s+commit/i.test(runBatSource), false);
});

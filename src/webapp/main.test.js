import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const mainSource = readFileSync(new URL('./main.cjs', import.meta.url), 'utf8');
const packageJson = JSON.parse(
  readFileSync(new URL('./package.json', import.meta.url), 'utf8'),
);

test('Electron main process constructs the bounded logger with process streams', () => {
  assert.match(
    mainSource,
    /const\s*\{\s*createBoundedLogger\s*\}\s*=\s*require\(['"]\.\/src\/utils\/boundedLogger\.cjs['"]\);/,
  );
  assert.match(
    mainSource,
    /const\s+log\s*=\s*createBoundedLogger\(\{\s*logFile,\s*consoleObject:\s*console,\s*stdout:\s*process\.stdout,\s*stderr:\s*process\.stderr,\s*\}\);/,
  );
});

test('Electron main process has no recursive inline file and console logger', () => {
  assert.doesNotMatch(mainSource, /function\s+writeLog\s*\(/);
  assert.doesNotMatch(mainSource, /fs\.appendFileSync\(logFile,/);
  assert.doesNotMatch(mainSource, /console\.(?:log|error)\(logEntry\)/);
});

test('Electron main process cleans logs only after obtaining the primary-instance lock', () => {
  const lockCall = 'const gotTheLock = app.requestSingleInstanceLock();';
  const lockIndex = mainSource.indexOf(lockCall);
  assert.notEqual(lockIndex, -1);

  const singleInstanceBranch = mainSource
    .slice(lockIndex + lockCall.length)
    .match(
      /^\s*if\s*\(!gotTheLock\)\s*\{(?<secondary>[\s\S]*?)\}\s*else\s*\{(?<primaryPrefix>[\s\S]*?)app\.on\('second-instance'/,
    );

  assert.ok(singleInstanceBranch, 'expected cleanup to be scoped by the single-instance branch');

  const { secondary, primaryPrefix } = singleInstanceBranch.groups;
  assert.doesNotMatch(secondary, /log\.cleanup\(\)/);
  assert.match(secondary, /log\.warn\(/);
  assert.match(secondary, /app\.quit\(\)/);

  const cleanupIndex = primaryPrefix.indexOf('log.cleanup();');
  const startupIndex = primaryPrefix.indexOf("log.info('Vantage Electron starting...');");
  assert.notEqual(cleanupIndex, -1);
  assert.notEqual(startupIndex, -1);
  assert.ok(cleanupIndex < startupIndex, 'cleanup must precede primary-instance startup logs');
  assert.equal(mainSource.match(/log\.cleanup\(\)/g)?.length, 1);
});

test('npm test explicitly runs the Electron main-process contract', () => {
  assert.match(packageJson.scripts.test, /(?:^|\s)main\.test\.js(?:\s|$)/);
  assert.match(packageJson.scripts.test, /vite\.config\.test\.js/);
  assert.match(packageJson.scripts.test, /package\.test\.js/);
  assert.match(packageJson.scripts.test, /src\/\*\*\/\*\.test\.js/);
});

test('Electron main window hides native chrome while keeping native window controls', () => {
  assert.ok(mainSource.includes('Menu.setApplicationMenu(null)'));
  assert.match(mainSource, /titleBarStyle\s*=\s*'hidden'/);
  assert.match(mainSource, /titleBarOverlay\s*=/);
  assert.ok(mainSource.includes('autoHideMenuBar: true'));
});

test('Electron main process exposes Settings IPC and restricts path opening', () => {
  assert.ok(mainSource.includes("ipcMain.handle('settings:get-state'"));
  assert.ok(mainSource.includes("ipcMain.handle('settings:save'"));
  assert.ok(mainSource.includes("ipcMain.handle('settings:open-path'"));
  assert.ok(mainSource.includes('saveSettingsPayload'));
  assert.ok(mainSource.includes('resolveAllowedSettingsPath'));
  assert.ok(mainSource.includes('settingsPathAllowlist'));
});

test('Electron main process requests macOS camera access before bundled backend startup', () => {
  assert.ok(mainSource.includes('systemPreferences'));
  assert.ok(mainSource.includes('session.defaultSession.setPermissionRequestHandler'));
  assert.ok(mainSource.includes("permission === 'media'"));
  assert.ok(mainSource.includes("requestedMediaTypes.includes('video')"));
  assert.ok(mainSource.includes('Approved renderer media permission request for camera priming'));
  assert.ok(mainSource.includes("CAMERA_PERMISSION_PRIME_CHANNEL = 'camera:prime-renderer-access'"));
  assert.ok(mainSource.includes("CAMERA_PERMISSION_RESULT_CHANNEL = 'camera:renderer-access-result'"));
  assert.ok(mainSource.includes('requestRendererCameraAccess'));
  assert.ok(mainSource.includes('mainWindow.webContents.send(CAMERA_PERMISSION_PRIME_CHANNEL)'));
  assert.ok(mainSource.includes("systemPreferences.getMediaAccessStatus('camera')"));
  assert.ok(mainSource.includes("systemPreferences.askForMediaAccess('camera')"));
  assert.ok(mainSource.includes('openMacosCameraPrivacySettings'));
  assert.ok(mainSource.includes('Privacy_Camera'));
  assert.ok(mainSource.includes('continuing backend startup'));
  assert.ok(mainSource.includes("CAMERA_FRAME_BRIDGE_START_CHANNEL = 'camera:start-frame-bridge'"));
  assert.ok(mainSource.includes("CAMERA_FRAME_CHANNEL = 'camera:renderer-frame'"));
  assert.ok(mainSource.includes("CAMERA_FRAME_BRIDGE_ERROR_CHANNEL = 'camera:frame-bridge-error'"));
  assert.ok(mainSource.includes("path: '/api/renderer_camera/frame'"));
  assert.ok(mainSource.includes("'x-vantage-intent': RENDERER_CAMERA_FRAME_INTENT"));
  assert.ok(mainSource.includes('Renderer camera access granted; confirming macOS camera media access'));
  assert.ok(mainSource.includes('Renderer camera frame capture failed'));
  assert.ok(mainSource.includes('startRendererCameraFrameBridge'));
  assert.ok(
    mainSource.indexOf('configureMediaPermissionHandler();')
      < mainSource.indexOf('        createWindow();'),
  );
  assert.ok(
    mainSource.indexOf('        createWindow();')
      < mainSource.indexOf('await requestMacosCameraAccess()'),
  );
  assert.ok(
    mainSource.indexOf('await requestMacosCameraAccess()')
      < mainSource.indexOf('ensureBundledBackendReady({'),
  );
  assert.ok(
    mainSource.indexOf('ensureBundledBackendReady({')
      < mainSource.indexOf('await startRendererCameraFrameBridge()'),
  );
});

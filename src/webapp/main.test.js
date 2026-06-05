import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const mainSource = readFileSync(new URL('./main.cjs', import.meta.url), 'utf8');

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

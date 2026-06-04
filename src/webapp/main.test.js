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
  assert.ok(mainSource.includes("systemPreferences.getMediaAccessStatus('camera')"));
  assert.ok(mainSource.includes("systemPreferences.askForMediaAccess('camera')"));
  assert.ok(mainSource.includes('openMacosCameraPrivacySettings'));
  assert.ok(mainSource.includes('Privacy_Camera'));
  assert.ok(mainSource.includes('continuing backend startup'));
  assert.ok(
    mainSource.indexOf('        createWindow();')
      < mainSource.indexOf('await requestMacosCameraAccess()'),
  );
  assert.ok(
    mainSource.indexOf('await requestMacosCameraAccess()')
      < mainSource.indexOf('ensureBundledBackendReady({'),
  );
});

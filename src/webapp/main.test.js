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

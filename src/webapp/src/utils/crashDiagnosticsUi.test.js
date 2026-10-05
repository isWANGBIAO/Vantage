import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

test('crash diagnostics UI has local privacy copy, interruption notice and narrow preload methods', () => {
  const read = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8');
  const copy = read('./displayCopy.js');
  for (const key of ['diagnostics.privacy', 'diagnostics.interrupted', 'diagnostics.open', 'diagnostics.dismiss']) {
    assert.equal(copy.split(`'${key}':`).length - 1, 2);
  }
  assert.match(read('../App.jsx'), /<CrashDiagnosticsNotice\s*\/>/);
  assert.match(read('../components/Settings.jsx'), /diagnostics\.openDirectory/);
  const preload = read('../../preload.cjs');
  assert.match(preload, /getDiagnosticsStatus: \(\) => ipcRenderer.invoke\('diagnostics:get-status'\)/);
  assert.match(preload, /openDiagnosticsDirectory: \(\) => ipcRenderer.invoke\('diagnostics:open-directory'\)/);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { resolveRuntimePaths } = require('./runtimePaths.cjs');

test('resolveRuntimePaths defaults packaged runs to LOCALAPPDATA Vantage directories', () => {
  const localAppData = path.win32.join('C:\\Users\\97012', 'AppData', 'Local');

  const runtimePaths = resolveRuntimePaths({
    appMode: 'packaged',
    env: { LOCALAPPDATA: localAppData },
    projectRoot: 'C:\\repo\\ai',
  });

  assert.equal(runtimePaths.appMode, 'packaged');
  assert.equal(runtimePaths.dataDir, path.win32.join(localAppData, 'Vantage'));
  assert.equal(runtimePaths.configDir, path.win32.join(localAppData, 'Vantage', 'config'));
  assert.equal(runtimePaths.historyDir, path.win32.join(localAppData, 'Vantage', 'history'));
  assert.equal(runtimePaths.logDir, path.win32.join(localAppData, 'Vantage', 'logs'));
  assert.equal(runtimePaths.plotDir, path.win32.join(localAppData, 'Vantage', 'plot_outputs'));
  assert.equal(runtimePaths.cacheDir, path.win32.join(localAppData, 'Vantage', 'cache'));
  assert.equal(runtimePaths.runtimeDir, path.win32.join(localAppData, 'Vantage', 'runtime'));
  assert.equal(runtimePaths.migrationDir, path.win32.join(localAppData, 'Vantage', 'migration'));
});

test('resolveRuntimePaths falls back to the project root in development mode', () => {
  const projectRoot = path.win32.join('C:\\repo', 'ai');

  const runtimePaths = resolveRuntimePaths({
    appMode: 'development',
    env: {},
    projectRoot,
  });

  assert.equal(runtimePaths.appMode, 'development');
  assert.equal(runtimePaths.dataDir, projectRoot);
  assert.equal(runtimePaths.configDir, path.win32.join(projectRoot, 'config'));
  assert.equal(runtimePaths.historyDir, path.win32.join(projectRoot, 'history'));
  assert.equal(runtimePaths.logDir, path.win32.join(projectRoot, 'logs'));
  assert.equal(runtimePaths.plotDir, path.win32.join(projectRoot, 'plot_outputs'));
  assert.equal(runtimePaths.cacheDir, path.win32.join(projectRoot, 'cache'));
  assert.equal(runtimePaths.runtimeDir, path.win32.join(projectRoot, 'runtime'));
  assert.equal(runtimePaths.migrationDir, path.win32.join(projectRoot, 'migration'));
});

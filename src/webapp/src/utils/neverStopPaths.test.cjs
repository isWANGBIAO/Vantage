const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

test('packaged Never Stop data uses the configured Vantage user data directory', () => {
  const { resolveNeverStopPaths } = require('./neverStopPaths.cjs');
  const paths = resolveNeverStopPaths({
    runtimePaths: { appMode: 'packaged', dataDir: path.join('C:', 'Users', 'User', 'AppData', 'Local', 'Vantage') },
    appDataDir: path.join('C:', 'Users', 'User', 'AppData', 'Roaming'),
    userDataDir: path.join('C:', 'Users', 'User', 'AppData', 'Roaming', 'vantage'),
  });
  assert.equal(paths.dataDir, path.join('C:', 'Users', 'User', 'AppData', 'Local', 'Vantage', 'never-stop'));
  assert.equal(paths.legacyDir, path.join('C:', 'Users', 'User', 'AppData', 'Roaming', 'VantageNeverStop'));
});

test('development Never Stop data stays outside the repository unless explicitly configured', () => {
  const { resolveNeverStopPaths } = require('./neverStopPaths.cjs');
  const base = {
    runtimePaths: { appMode: 'development', dataDir: path.join('D:', 'repo', 'Vantage') },
    appDataDir: path.join('C:', 'Users', 'User', 'AppData', 'Roaming'),
    userDataDir: path.join('C:', 'Users', 'User', 'AppData', 'Roaming', 'vantage'),
  };
  assert.equal(resolveNeverStopPaths(base).dataDir, path.join(base.userDataDir, 'never-stop'));
  assert.equal(resolveNeverStopPaths({ ...base, env: { VANTAGE_DATA_DIR: base.runtimePaths.dataDir } }).dataDir,
    path.join(base.runtimePaths.dataDir, 'never-stop'));
});

test('the former Never Stop data override remains the migration source', () => {
  const { resolveNeverStopPaths } = require('./neverStopPaths.cjs');
  const override = path.join('D:', 'custom', 'never-stop');
  const paths = resolveNeverStopPaths({
    runtimePaths: { appMode: 'packaged', dataDir: path.join('C:', 'Vantage') },
    appDataDir: path.join('C:', 'Roaming'),
    userDataDir: path.join('C:', 'Vantage'),
    env: { NEVER_STOP_DATA_DIR: override },
  });
  assert.equal(paths.legacyDir, override);
});

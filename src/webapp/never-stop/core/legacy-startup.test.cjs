const test = require('node:test');
const assert = require('node:assert/strict');

test('retiring the old Windows startup item touches only the Never Stop name', async () => {
  const { retireLegacyStartup } = require('./legacy-startup.cjs');
  const calls = [];
  let command = 'old portable executable';
  const removed = await retireLegacyStartup({
    app: { isPackaged: true, setLoginItemSettings: value => { calls.push(value); command = null; } },
    platform: 'win32',
    readRegistration: async name => { assert.equal(name, 'com.vantage.never-stop'); return { command }; },
  });
  assert.equal(removed, true);
  assert.deepEqual(calls, [{ openAtLogin: false, name: 'com.vantage.never-stop' }]);
});

test('legacy startup cleanup leaves missing registrations and development runs alone', async () => {
  const { retireLegacyStartup } = require('./legacy-startup.cjs');
  const app = { isPackaged: true, setLoginItemSettings: () => { throw Error('unexpected write'); } };
  assert.equal(await retireLegacyStartup({ app, platform: 'win32', readRegistration: async () => ({ command: null }) }), false);
  assert.equal(await retireLegacyStartup({ app: { ...app, isPackaged: false }, platform: 'win32' }), false);
});

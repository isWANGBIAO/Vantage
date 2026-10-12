const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

test('Vantage owns one page-independent Never Stop service and releases its runner on exit', async () => {
  const { createVantageNeverStopService } = require('./vantage-service.cjs');
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'vantage-never-stop-service-'));
  const dataDir = path.join(root, 'never-stop');
  const legacyDir = path.join(root, 'legacy');
  const options = {
    dataDir,
    legacyDir,
    appVersion: '1.0.88',
    safeStorage: { isEncryptionAvailable: () => false },
    Notification: { isSupported: () => false },
    pickDirectory: async () => null,
    testNotification: async () => ({ status: 'requested' }),
    onOpen: () => {},
    onChange: () => {},
  };
  let first;
  let second;
  try {
    first = await createVantageNeverStopService(options);
    const state = await first.invoke('state');
    assert.equal(state.appVersion, '1.0.88');
    assert.deepEqual(state.projects, []);
    await assert.rejects(createVantageNeverStopService(options), /runner is already active|Runner lock|EADDRINUSE/i);
    await first.shutdown({ preserveIntent: true });
    second = await createVantageNeverStopService(options);
    assert.deepEqual((await second.invoke('state')).projects, []);
  } finally {
    await second?.shutdown({ preserveIntent: true });
    await first?.shutdown({ preserveIntent: true });
    await fs.rm(root, { recursive: true, force: true });
  }
});

test('Never Stop migration failure leaves the Vantage application available and reports the page error', async () => {
  const { createVantageNeverStopService } = require('./vantage-service.cjs');
  await assert.rejects(createVantageNeverStopService({
    dataDir: '/unused',
    legacyDir: '/unused',
    prepareData: async () => { throw new Error('legacy instance is running'); },
  }), /legacy instance is running/);
});

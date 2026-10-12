const test = require('node:test');
const assert = require('node:assert/strict');

test('Never Stop bridge accepts only the trusted Vantage main frame', async () => {
  const { installNeverStopBridge } = require('./neverStopBridge.cjs');
  const handlers = new Map();
  const sent = [];
  const frame = { url: 'vantage://app/index.html' };
  const contents = { mainFrame: frame, send: (...args) => sent.push(args) };
  const ipcMain = { handle: (name, handler) => handlers.set(name, handler) };
  const calls = [];
  const bridge = installNeverStopBridge({
    ipcMain,
    getWebContents: () => contents,
    isTrustedDocument: url => url === 'vantage://app/index.html',
    getService: () => ({ invoke: async (...args) => { calls.push(args); return { projects: [] }; } }),
  });
  const invoke = handlers.get('never-stop:invoke');
  assert.deepEqual(await invoke({ sender: contents, senderFrame: frame }, 'state', {}), {
    ok: true, value: { projects: [] },
  });
  assert.deepEqual(calls, [['state', {}]]);
  assert.equal((await invoke({ sender: {}, senderFrame: frame }, 'state', {})).ok, false);
  assert.equal((await invoke({ sender: contents, senderFrame: { url: frame.url } }, 'state', {})).ok, false);
  assert.equal(calls.length, 1);
  bridge.broadcast({ selectedProjectId: 'project-1' });
  assert.deepEqual(sent, [['never-stop:change', { selectedProjectId: 'project-1' }]]);
});

test('Never Stop bridge reports unavailable service and bounded operation errors', async () => {
  const { installNeverStopBridge } = require('./neverStopBridge.cjs');
  let handler;
  const frame = { url: 'http://localhost:5173/' };
  const contents = { mainFrame: frame };
  let service = null;
  installNeverStopBridge({
    ipcMain: { handle: (_name, value) => { handler = value; } },
    getWebContents: () => contents,
    isTrustedDocument: () => true,
    getService: () => service,
  });
  const unavailable = await handler({ sender: contents, senderFrame: frame }, 'state', {});
  assert.equal(unavailable.ok, false);
  assert.match(unavailable.error, /Never Stop/);
  service = { invoke: async () => { throw new Error('x'.repeat(3000)); } };
  const failed = await handler({ sender: contents, senderFrame: frame }, 'state', {});
  assert.equal(failed.ok, false);
  assert.equal(failed.error.length, 2000);
});

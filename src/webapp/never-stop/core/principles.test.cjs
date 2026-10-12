const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { PrinciplesStore } = require('./principles.cjs');
const { Application } = require('./application.cjs');

async function fixture(t, options = {}) {
  const dataDir = await fs.mkdtemp(path.join(os.tmpdir(), 'never-stop-principles-'));
  t.after(() => fs.rm(dataDir, { recursive: true, force: true }));
  const store = new PrinciplesStore({ dataDir, defaultText: 'default principles', ...options });
  await store.init();
  return { dataDir, store };
}

test('principles persist under user data and reload across restarts and template upgrades', async t => {
  const { dataDir, store } = await fixture(t);
  const original = store.snapshot();
  assert.equal(original.text, 'default principles');
  const saved = await store.save('custom principles 中文', original.version);
  const restarted = new PrinciplesStore({ dataDir, defaultText: 'new packaged default' });
  await restarted.init();
  assert.equal(restarted.snapshot().text, saved.text);
  assert.equal(restarted.snapshot().defaultText, 'new packaged default');
  assert.equal(await fs.readFile(path.join(dataDir, 'execution-principles.md'), 'utf8'), saved.text);
});

test('concurrent and external changes reject stale edits without overwriting either draft', async t => {
  const { dataDir, store } = await fixture(t);
  const base = store.snapshot().version;
  const result = await Promise.allSettled([store.save('first', base), store.save('second', base)]);
  assert.equal(result[0].status, 'fulfilled');
  assert.equal(result[1].status, 'rejected');
  assert.match(result[1].reason.message, /冲突/);
  const nextBase = store.snapshot().version;
  await fs.writeFile(path.join(dataDir, 'execution-principles.md'), 'external');
  await assert.rejects(store.save('local', nextBase), /冲突/);
  assert.equal((await store.read()).text, 'external');
});

test('invalid text and failed writes preserve active principles', async t => {
  const { store } = await fixture(t, { write: async () => { throw Error('disk failure'); } });
  const before = store.snapshot();
  for (const text of ['', '  ', null, '中'.repeat(400000)])
    await assert.rejects(store.save(text, before.version), /原则/);
  await assert.rejects(store.save('changed', before.version), /disk failure/);
  assert.deepEqual(store.snapshot(), before);
});

test('application displays and executes saved principles and loads them before runner recovery', async t => {
  const { dataDir } = await fixture(t);
  const runner = new EventEmitter();
  runner.snapshot = () => [];
  const app = new Application({ runner, dataDir, principles: 'default principles', resources: { list: () => [] } });
  await app.init();
  const before = await app.invoke('principles.read');
  await app.invoke('principles.save', { text: 'new rules', version: before.version });
  assert.equal((await app.invoke('state')).principles, 'new rules');
  assert.equal(runner.principles, 'new rules');
  await assert.rejects(app.invoke('principles.save', { text: 'stale', version: before.version }), /冲突/);
  assert.equal(runner.principles, 'new rules');
  const saved = await app.invoke('principles.read');
  app.principlesStore.write = async () => { throw Error('write unavailable'); };
  await assert.rejects(app.invoke('principles.save', { text: 'unpersisted rules', version: saved.version }), /write unavailable/);
  assert.equal((await app.invoke('state')).principles, 'new rules');
  assert.equal(runner.principles, 'new rules');
  const restartedRunner = new EventEmitter();
  restartedRunner.snapshot = () => [];
  const restartedApp = new Application({ runner: restartedRunner, dataDir, principles: 'default principles' });
  await restartedApp.init();
  assert.equal(restartedRunner.principles, 'new rules');
});

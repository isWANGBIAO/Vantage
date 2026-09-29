const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { launchOwned, terminateOwned } = require('./process-owner.cjs');

async function invoke(t, events, { newline = true, exitCode = 0, stderr = '' } = {}) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'never-stop-completion-'));
  const fixture = path.join(root, 'cli.cjs');
  const output = events.map(event => JSON.stringify(event)).join('\n') + (newline ? '\n' : '');
  await fs.writeFile(fixture, `process.stdin.resume(); process.stdin.on('end', () => { process.stderr.write(${JSON.stringify(stderr)}); process.stdout.write(${JSON.stringify(output)}); process.exitCode = ${exitCode}; });`);
  const seen = [];
  const h = launchOwned({ command: process.execPath, args: [fixture], backend: 'claude' }, root, 'synthetic diagnostic', randomUUID(), event => seen.push(event));
  t.after(async () => { await terminateOwned(h.record, { trusted: true }); await fs.rm(root, { recursive: true, force: true }); });
  h.send();
  return { done: await h.done, seen };
}
test('Claude exiting zero after message_stop without final result is an incomplete call', async t => {
  const { done } = await invoke(t, [{ type: 'stream_event', event: { type: 'message_stop' } }]);
  assert.notEqual(done.code, 0);
  assert.match(done.error, /未收到.*result|不完整/);
});
test('Claude result error cannot be successful even if CLI exits zero', async t => {
  const { done } = await invoke(t, [{ type: 'result', subtype: 'error_during_execution', is_error: true, errors: ['connection interrupted'] }]);
  assert.notEqual(done.code, 0);
  assert.match(done.error, /connection interrupted/);
});
test('final successful result without a trailing newline completes the call', async t => {
  const { done, seen } = await invoke(t, [{ type: 'result', subtype: 'success', is_error: false, result: 'OK' }], { newline: false });
  assert.equal(done.code, 0);
  assert.equal(done.error, '');
  assert.ok(seen.some(event => event.entries?.some(entry => entry.text === '本轮调用结束')));
});
test('partial thinking event reaches output before process completion', async t => {
  const { seen } = await invoke(t, [{ type: 'stream_event', event: { type: 'content_block_delta', delta: { type: 'thinking_delta', thinking: 'PRIVATE' } } }, { type: 'result', subtype: 'success', is_error: false }]);
  const entries = seen.filter(event => event.type === 'output').flatMap(event => event.entries);
  assert.ok(entries.some(entry => /思考/.test(entry.text)));
  assert.ok(!JSON.stringify(entries).includes('PRIVATE'));
});
test('final successful result supersedes a recoverable earlier error event', async t => {
  const { done, seen } = await invoke(t, [
    { type: 'stream_event', event: { type: 'error', error: { message: 'temporary disconnection' } } },
    { type: 'result', subtype: 'success', is_error: false, result: 'recovered' },
  ]);
  assert.equal(done.code, 0);
  assert.equal(done.error, '');
  assert.ok(seen.some(event => event.entries?.some(entry => entry.text.includes('temporary disconnection'))));
});
test('a bounded long final result above 64 KiB is not mistaken for an incomplete stream', async t => {
  const { done } = await invoke(t, [{ type: 'result', subtype: 'success', is_error: false, result: 'x'.repeat(100000) }]);
  assert.equal(done.code, 0);
  assert.equal(done.error, '');
});

test('model catalog warning is neutral during a successful real worker call', async t => {
  const { done, seen } = await invoke(t, [{ type: 'result', subtype: 'success', is_error: false }], {
    stderr: '[claude-code:unrecognized_model] {"model":"custom-model","query_source":"compact"}\n',
  });
  assert.equal(done.code, 0);
  assert.equal(done.error, '');
  const entries = seen.flatMap(event => event.entries || []);
  assert.ok(entries.some(entry => entry.kind === 'status' && /内置.*列表/.test(entry.text)));
  assert.ok(!entries.some(entry => entry.kind === 'error'));
});

test('model catalog warning never turns a failed worker into success', async t => {
  const { done, seen } = await invoke(t, [], {
    exitCode: 1,
    stderr: '[claude-code:unrecognized_model] {"model":"custom-model","query_source":"compact"}\nAPI Error: 400 context exceeded\n',
  });
  assert.notEqual(done.code, 0);
  assert.match(done.error, /API Error: 400/);
  assert.ok(seen.some(event => event.entries?.some(entry => entry.kind === 'error' && /API Error: 400/.test(entry.text))));
});

test('a later model warning does not replace the real failure detail', async t => {
  const { done } = await invoke(t, [], {
    exitCode: 1,
    stderr: 'API Error: 500 failed\n[claude-code:unrecognized_model] {"model":"custom-model","query_source":"sdk"}\n',
  });
  assert.notEqual(done.code, 0);
  assert.match(done.error, /API Error: 500/);
});

test('a failed exit with only the model warning still fails without blaming the model name', async t => {
  const { done } = await invoke(t, [], {
    exitCode: 1,
    stderr: '[claude-code:unrecognized_model] {"model":"custom-model","query_source":"sdk"}\n',
  });
  assert.notEqual(done.code, 0);
  assert.doesNotMatch(done.error, /unrecognized_model|custom-model|内置.*列表/);
});

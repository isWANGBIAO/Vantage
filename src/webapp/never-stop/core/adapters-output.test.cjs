const test = require('node:test');
const assert = require('node:assert/strict');
const { createLineReader, buildInvocation } = require('./adapters.cjs');
test('live protocol preserves UTF-8 characters split across pipe chunks', () => {
  const lines = [];
  const read = createLineReader(line => lines.push(line));
  const bytes = Buffer.from('正在读取文件 🔎\n');
  for (const byte of bytes) read(Buffer.from([byte]));
  assert.deepEqual(lines, ['正在读取文件 🔎']);
});
test('Claude requests partial events without overriding the selected model or permissions', () => {
  for (const sessionId of [null, 'existing-session']) {
    const { args } = buildInvocation({ backend: 'claude', sessionId }, 'claude');
    assert.ok(args.includes('--include-partial-messages'));
    assert.ok(!args.includes('--model'));
    assert.ok(!args.includes('--permission-mode'));
  }
});
test('line reader flushes the final unterminated JSON event exactly once', () => {
  const lines = [];
  const read = createLineReader(line => lines.push(line));
  read(Buffer.from('{"type":"result","result":"完成"}'));
  read.flush();
  read.flush();
  assert.deepEqual(lines, ['{"type":"result","result":"完成"}']);
});

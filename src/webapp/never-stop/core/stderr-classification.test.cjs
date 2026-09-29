const test = require('node:test');
const assert = require('node:assert/strict');
const { stderrEntry, createStderrReader } = require('./live-output.cjs');

const warning = (model = 'custom-model', query_source = 'compact') =>
  `[claude-code:unrecognized_model] ${JSON.stringify({ model, query_source })}`;

test('known Claude model catalog warning is an explanatory status, not an API failure', () => {
  for (const source of ['compact', 'sdk']) {
    const entries = stderrEntry(warning('custom-model', source) + '\r\n');
    assert.equal(entries.length, 1);
    assert.equal(entries[0].kind, 'status');
    assert.match(entries[0].text, /custom-model/);
    assert.match(entries[0].text, /内置.*列表/);
    assert.match(entries[0].text, /不表示调用失败/);
  }
});

test('real failures and malformed or mixed model warnings remain errors', () => {
  for (const line of [
    'API Error: 400 ContextWindowExceededError',
    'API Error: 404 model not found',
    'warning: connection failed',
    '[claude-code:unrecognized_model] not JSON',
    '[claude-code:unrecognized_model] {"model":"custom-model"}',
    '[claude-code:unrecognized_model] {"model":null,"query_source":"compact"}',
    '[claude-code:unrecognized_model] {"model":"custom-model","query_source":"compact","error":"failed"}',
    warning() + '\nAPI Error: 500 failed',
    warning() + ' API Error: 500 failed',
    warning('bad\nAPI Error: 500 failed'),
    warning('x'.repeat(5000)),
  ]) assert.equal(stderrEntry(line)[0].kind, 'error', line.slice(0, 120));
});

test('model warning display retains credential redaction', () => {
  const entry = stderrEntry(warning('custom-PRIVATE_EXACT-sk-testcredential'), ['PRIVATE_EXACT'])[0];
  assert.equal(entry.kind, 'status');
  assert.ok(!entry.text.includes('PRIVATE_EXACT'));
  assert.ok(!entry.text.includes('sk-testcredential'));
});

test('fragmented UTF-8 warning and following real error retain distinct classifications', () => {
  const entries = [];
  const read = createStderrReader(batch => entries.push(...batch));
  const bytes = Buffer.from(warning('中文模型') + '\r\nAPI Error: 400 context exceeded\n');
  for (const byte of bytes) read(Buffer.from([byte]));
  read.flush();
  assert.deepEqual(entries.map(entry => entry.kind), ['status', 'error']);
  assert.match(entries[0].text, /中文模型/);
  assert.match(entries[1].text, /API Error: 400/);
});

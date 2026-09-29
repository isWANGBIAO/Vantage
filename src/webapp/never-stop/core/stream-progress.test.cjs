const test = require('node:test');
const assert = require('node:assert/strict');
const { createDisplayParser } = require('./live-output.cjs');
const wrap = event => ({ type: 'stream_event', event });

test('stream activity appears while thinking and never exposes private reasoning or token fragments', () => {
  let now = 0;
  const parse = createDisplayParser({ now: () => now, secrets: ['split-secret'] });
  const entries = [];
  entries.push(...parse(wrap({ type: 'message_start', message: { id: 'm1' } })));
  entries.push(...parse(wrap({ type: 'content_block_start', index: 0, content_block: { type: 'thinking' } })));
  entries.push(...parse(wrap({ type: 'content_block_delta', index: 0, delta: { type: 'thinking_delta', thinking: 'PRIVATE_REASONING' } })));
  now = 5000;
  entries.push(...parse(wrap({ type: 'content_block_delta', index: 0, delta: { type: 'thinking_delta', thinking: 'MORE_PRIVATE' } })));
  assert.ok(entries.some(entry => /思考/.test(entry.text)));
  assert.ok(entries.some(entry => entry.text.includes(`已接收 ${'PRIVATE_REASONINGMORE_PRIVATE'.length} 字符`)), JSON.stringify(entries));
  assert.ok(!JSON.stringify(entries).includes('PRIVATE'));
  entries.push(...parse(wrap({ type: 'content_block_start', index: 1, content_block: { type: 'text' } })));
  for (const text of ['split-', 'secret']) entries.push(...parse(wrap({ type: 'content_block_delta', index: 1, delta: { type: 'text_delta', text } })));
  assert.ok(entries.some(entry => /生成回复/.test(entry.text)));
  assert.ok(!JSON.stringify(entries).includes('split-'));
  assert.ok(!entries.some(entry => entry.kind === 'assistant'));
  entries.push(...parse({ type: 'assistant', message: { content: [{ type: 'text', text: 'safe split-secret answer' }] } }));
  entries.push(...parse(wrap({ type: 'content_block_stop', index: 1 })));
  assert.deepEqual(entries.filter(entry => entry.kind === 'assistant'), [{ kind: 'assistant', text: 'safe [已隐藏] answer' }]);
});

test('high frequency stream input has bounded activity without buffering raw content', () => {
  const parse = createDisplayParser({ now: () => 0 });
  const entries = [];
  for (let i = 0; i < 50000; i++) entries.push(...parse(wrap({ type: 'content_block_delta', index: i, delta: { type: 'text_delta', text: 'x'.repeat(100) } })));
  assert.ok(entries.length <= 2, `Unexpected activity flood: ${entries.length}`);
});

test('tool input, compaction and error events report safe activity, not raw tool JSON', () => {
  const parse = createDisplayParser();
  const entries = [
    ...parse(wrap({ type: 'content_block_start', index: 0, content_block: { type: 'tool_use', name: 'PRIVATE_NAME' } })),
    ...parse(wrap({ type: 'content_block_delta', index: 0, delta: { type: 'input_json_delta', partial_json: '{"password":"PRIVATE_VALUE"}' } })),
    ...parse({ type: 'system', subtype: 'status', status: 'compacting' }),
    ...parse({ type: 'system', subtype: 'compact_boundary' }),
    ...parse(wrap({ type: 'error', error: { message: 'upstream disconnected' } })),
  ];
  assert.ok(entries.some(entry => /工具/.test(entry.text)));
  assert.ok(entries.some(entry => /压缩/.test(entry.text)));
  assert.ok(entries.some(entry => entry.kind === 'error' && entry.text.includes('disconnected')));
  assert.ok(!JSON.stringify(entries).includes('PRIVATE'));
});

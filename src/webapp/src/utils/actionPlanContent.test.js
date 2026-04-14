import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  normalizeActionPlanContent,
  shouldRenderActionPlanAsPlainText,
  toPlainTextActionPlanContent,
} from './actionPlanContent.js';

const actionPlanContentSource = readFileSync(new URL('./actionPlanContent.js', import.meta.url), 'utf8');

test('normalizeActionPlanContent removes broken html fragments', () => {
  const raw = `### Summary
| Nutrition | Keep this line <b<br>> <b<br>> <b<b<b<
### |
* * *`;

  const normalized = normalizeActionPlanContent(raw);

  assert.match(normalized, /Summary/);
  assert.match(normalized, /Keep this line/);
  assert.doesNotMatch(normalized, /<b<br>>/);
  assert.doesNotMatch(normalized, /^### \|$/m);
});

test('normalizeActionPlanContent strips common html tags and empty marker lines', () => {
  const raw = `| | | |
#### #### #### ####
** ** ** **
<p>Task</p><ul><li>Line one</li></ul>
Value A<br>Value B`;

  const normalized = normalizeActionPlanContent(raw);

  assert.doesNotMatch(normalized, /^\| \| \| \|$/m);
  assert.doesNotMatch(normalized, /^#### #### #### ####$/m);
  assert.doesNotMatch(normalized, /^\*\* \*\* \*\* \*\*$/m);
  assert.doesNotMatch(normalized, /<p>|<br>|<li>|<ul>/);
  assert.match(normalized, /Task - Line one/);
  assert.match(normalized, /Value A Value B/);
});

test('normalizeActionPlanContent preserves trailing text after inline corruption markers', () => {
  const raw = `* ✅️<b<br>> 固定起床时间，不补觉拖延。
1. ⚠️<b<br>> 今天先确认团队碰头是否同步。
|[21:00]<b<br>> *硬性边界*|<b<br>> **[P0]【开启夜间模式】**<b<br>> •手机电脑台灯切换至夜间模式。`;

  const normalized = normalizeActionPlanContent(raw);

  assert.match(normalized, /固定起床时间，不补觉拖延。/);
  assert.match(normalized, /今天先确认团队碰头是否同步。/);
  assert.match(normalized, /手机电脑台灯切换至夜间模式。/);
  assert.doesNotMatch(normalized, /<b<br>>/);
});

test('normalizeActionPlanContent removes inline b residue without dropping following text', () => {
  const normalized = normalizeActionPlanContent(
    '• 晚间准备：<b<b<b<b<b<bbbbbbbbbbbbb 保留后面的正文。',
  );

  assert.match(normalized, /保留后面的正文。/);
  assert.doesNotMatch(normalized, /bbbbbbbb/);
});

test('normalizeActionPlanContent unwraps fenced markdown documents', () => {
  const raw = '```markdown\n# Plan\n\n- Item\n```';

  const normalized = normalizeActionPlanContent(raw);

  assert.equal(normalized, '# Plan\n\n- Item');
});

test('normalizeActionPlanContent unwraps in-progress fenced markdown streams', () => {
  const raw = '```markdown\n# Plan\n\n- Item';

  const normalized = normalizeActionPlanContent(raw);

  assert.equal(normalized, '# Plan\n\n- Item');
});

test('shouldRenderActionPlanAsPlainText flags remaining html-like corruption', () => {
  assert.equal(
    shouldRenderActionPlanAsPlainText('Valid text <stronG still hanging around'),
    true,
  );
  assert.equal(
    shouldRenderActionPlanAsPlainText('## Heading\n\n- Normal bullet list'),
    false,
  );
});

test('toPlainTextActionPlanContent converts html fragments into readable text', () => {
  const plainText = toPlainTextActionPlanContent('<p>Alpha</p><ul><li>Beta</li></ul>');

  assert.match(plainText, /Alpha/);
  assert.match(plainText, /- Beta/);
  assert.doesNotMatch(plainText, /<p>|<li>/);
});

test('actionPlanContent no longer exposes delimiter splitters or thinking fallback helpers', () => {
  assert.equal(actionPlanContentSource.includes('splitActionPlanContent'), false);
  assert.equal(actionPlanContentSource.includes('coalesceActionPlanReplyContent'), false);
});

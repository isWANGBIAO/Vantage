import test from 'node:test';
import assert from 'node:assert/strict';

import {
  normalizeActionPlanContent,
  shouldRenderActionPlanAsPlainText,
  splitActionPlanContent,
  toPlainTextActionPlanContent,
} from './actionPlanContent.js';

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

test('splitActionPlanContent keeps both sections around analysis separator', () => {
  const sections = splitActionPlanContent('Analysis\n\n---ANALYSIS_END---\n\nPlan');

  assert.equal(sections.analysis, 'Analysis');
  assert.equal(sections.plan, 'Plan');
});

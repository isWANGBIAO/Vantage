import assert from 'node:assert/strict';
import test from 'node:test';
import { getActionPlanRenderState, normalizeActionPlanContent } from './actionPlanContent.js';

test('render normalization preserves nested lists, code whitespace and hard breaks', () => {
  const markdown = '# Plan\n- Parent\n    - Child\n        - Grandchild\n\n```python\nif ready:\n    print("<p>literal</p>")\n\n\n\n    keep = "a  b"\n```\n\nLine with hard break  \nNext line';
  assert.equal(normalizeActionPlanContent(markdown), markdown);
});

test('indented code preserves the first and last indentation', () => {
  const markdown = '    first  line\n    <p>literal</p>\n    second  line';
  assert.equal(normalizeActionPlanContent(markdown), markdown);
});

test('literal HTML inside code does not force the whole plan into plain text', () => {
  const markdown = '# Plan\n```html\n<p>literal</p>\n```\n- Next task';
  const state = getActionPlanRenderState(markdown);
  assert.equal(state.plainText, false);
  assert.equal(state.markdownContent, markdown);
});

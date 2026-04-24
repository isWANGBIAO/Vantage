import test from 'node:test';
import assert from 'node:assert/strict';

import { formatModelReasoningSupportLabel, parseModelReasoningSupport } from './modelReasoningSupport.js';

test('formatModelReasoningSupportLabel uses localized suffix copy', () => {
  const support = { 'gpt-test': false };
  const t = (key) => {
    if (key === 'common.reasoning.unsupported_suffix') {
      return ' (reasoning unsupported)';
    }
    return key;
  };

  assert.equal(formatModelReasoningSupportLabel('gpt-test', support, t), ' (reasoning unsupported)');
});

test('parseModelReasoningSupport reads provider model capabilities', () => {
  assert.deepEqual(
    parseModelReasoningSupport([
      {
        model_capabilities: {
          plain: [],
          thinking: ['reasoning-effort'],
        },
      },
    ]),
    {
      plain: false,
      thinking: true,
    },
  );
});

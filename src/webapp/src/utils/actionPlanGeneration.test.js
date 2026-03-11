import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildActionPlanGenerationPayload,
  shouldAutogenerateActionPlan,
} from './actionPlanGeneration.js';

test('buildActionPlanGenerationPayload normalizes reasoning and can replace today', () => {
  assert.deepEqual(
    buildActionPlanGenerationPayload('invalid', { replaceToday: true }),
    {
      reasoning_effort: 'medium',
      replace_today: true,
    },
  );
});

test('shouldAutogenerateActionPlan only allows one startup run', () => {
  assert.equal(
    shouldAutogenerateActionPlan({
      hasTriggered: false,
      isGenerating: false,
      isAborted: false,
    }),
    true,
  );

  assert.equal(
    shouldAutogenerateActionPlan({
      hasTriggered: true,
      isGenerating: false,
      isAborted: false,
    }),
    false,
  );

  assert.equal(
    shouldAutogenerateActionPlan({
      hasTriggered: false,
      isGenerating: true,
      isAborted: false,
    }),
    false,
  );

  assert.equal(
    shouldAutogenerateActionPlan({
      hasTriggered: false,
      isGenerating: false,
      isAborted: true,
    }),
    false,
  );
});

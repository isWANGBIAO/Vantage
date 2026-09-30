import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildActionPlanGenerationPayload,
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

test('buildActionPlanGenerationPayload includes provider-aware model selection', () => {
  assert.deepEqual(
    buildActionPlanGenerationPayload('high', {
      model: 'gpt-5.5',
      providerRoute: 'custom',
    }),
    {
      reasoning_effort: 'high',
      replace_today: false,
      model: 'gpt-5.5',
      provider_route: 'custom',
    },
  );
});

test('buildActionPlanGenerationPayload includes fast priority tier only for supported GPT proxy models', () => {
  assert.deepEqual(
    buildActionPlanGenerationPayload('high', {
      model: 'gpt-5.5',
      providerRoute: 'custom',
      fastModeEnabled: true,
    }),
    {
      reasoning_effort: 'high',
      replace_today: false,
      model: 'gpt-5.5',
      provider_route: 'custom',
      service_tier: 'priority',
    },
  );

  assert.deepEqual(
    buildActionPlanGenerationPayload('high', {
      model: 'deepseek-v4-pro',
      providerRoute: 'deepseek',
      fastModeEnabled: true,
    }),
    {
      reasoning_effort: 'high',
      replace_today: false,
      model: 'deepseek-v4-pro',
      provider_route: 'deepseek',
    },
  );
});

test('buildActionPlanGenerationPayload maps reasoning for DeepSeek V4 models', () => {
  assert.deepEqual(
    buildActionPlanGenerationPayload('xhigh', {
      model: 'deepseek-flash',
      providerRoute: 'DeepSeek',
    }),
    {
      reasoning_effort: 'high',
      replace_today: false,
      model: 'deepseek-flash',
      provider_route: 'DeepSeek',
    },
  );

  assert.deepEqual(
    buildActionPlanGenerationPayload('max', {
      model: 'deepseek-flash',
      providerRoute: 'DeepSeek',
    }),
    {
      reasoning_effort: 'max',
      replace_today: false,
      model: 'deepseek-flash',
      provider_route: 'DeepSeek',
    },
  );
});

test('buildActionPlanGenerationPayload recognizes versioned DeepSeek V4 Flash', () => {
  assert.deepEqual(
    buildActionPlanGenerationPayload('medium', {
      model: 'DeepSeek-V4-Flash-0731',
      providerRoute: 'custom',
    }),
    {
      reasoning_effort: 'high',
      replace_today: false,
      model: 'DeepSeek-V4-Flash-0731',
      provider_route: 'custom',
    },
  );
});

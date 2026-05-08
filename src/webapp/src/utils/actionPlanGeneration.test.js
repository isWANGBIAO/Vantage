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
      model: 'deepseek-v4-pro',
      providerRoute: 'deepseek',
    }),
    {
      reasoning_effort: 'max',
      replace_today: false,
      model: 'deepseek-v4-pro',
      provider_route: 'deepseek',
    },
  );
});

test('buildActionPlanGenerationPayload can request provider readiness wait for startup auto generation', () => {
  assert.deepEqual(
    buildActionPlanGenerationPayload('xhigh', {
      replaceToday: true,
      model: 'gpt-5.5',
      providerRoute: 'custom',
      startupAutoGenerate: true,
      fastModeEnabled: true,
    }),
    {
      reasoning_effort: 'xhigh',
      replace_today: true,
      model: 'gpt-5.5',
      provider_route: 'custom',
      service_tier: 'priority',
      wait_for_provider_ready: true,
    },
  );
});

test('shouldAutogenerateActionPlan only allows startup runs when the setting is enabled', () => {
  assert.equal(
    shouldAutogenerateActionPlan({
      autoGenerateEnabled: true,
      hasTriggered: false,
      isGenerating: false,
      isAborted: false,
    }),
    true,
  );

  assert.equal(
    shouldAutogenerateActionPlan({
      autoGenerateEnabled: false,
      hasTriggered: false,
      isGenerating: false,
      isAborted: false,
    }),
    false,
  );

  assert.equal(
    shouldAutogenerateActionPlan({
      autoGenerateEnabled: true,
      hasTriggered: true,
      isGenerating: false,
      isAborted: false,
    }),
    false,
  );

  assert.equal(
    shouldAutogenerateActionPlan({
      autoGenerateEnabled: true,
      hasTriggered: false,
      isGenerating: true,
      isAborted: false,
    }),
    false,
  );

  assert.equal(
    shouldAutogenerateActionPlan({
      autoGenerateEnabled: true,
      hasTriggered: false,
      isGenerating: false,
      isAborted: true,
    }),
    false,
  );

  assert.equal(
    shouldAutogenerateActionPlan({
      autoGenerateEnabled: true,
      hasTriggered: false,
      isGenerating: false,
      isAborted: false,
      hasExistingPlan: true,
    }),
    false,
  );

  assert.equal(
    shouldAutogenerateActionPlan({
      autoGenerateEnabled: true,
      hasTriggered: false,
      isGenerating: false,
      isAborted: false,
      loadFailed: true,
    }),
    false,
  );
});

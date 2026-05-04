import test from 'node:test';
import assert from 'node:assert/strict';

import {
  computeDisplayedDurationSeconds,
  formatActionPlanCacheBreakdown,
  formatActionPlanTokenBreakdown,
  formatThinkingTitleWithDuration,
  formatPoweredByLabel,
  formatReasoningEffortLabel,
  getActionPlanRoundStats,
  isFallbackExecution,
} from './actionPlanStats.js';

test('formatPoweredByLabel prefers model and provider display name', () => {
  assert.equal(
    formatPoweredByLabel({
      model: 'gpt-5.2',
      provider_route: 'cliproxyapi_primary',
    }),
    'gpt-5.2 | CLIProxyAPI',
  );
});

test('formatReasoningEffortLabel maps xhigh to Extra High', () => {
  assert.equal(
    formatReasoningEffortLabel('xhigh'),
    'Extra High',
  );
});

test('formatReasoningEffortLabel treats default mode as Medium default', () => {
  assert.equal(formatReasoningEffortLabel('default'), 'Medium');
});

test('computeDisplayedDurationSeconds uses live elapsed time while active', () => {
  assert.equal(
    computeDisplayedDurationSeconds(
      {
        total_duration: 0,
        startTime: 10_000,
      },
      {
        isActive: true,
        nowMs: 13_500,
      },
    ),
    3.5,
  );
});

test('computeDisplayedDurationSeconds keeps the larger backend duration when it is already available', () => {
  assert.equal(
    computeDisplayedDurationSeconds(
      {
        total_duration: 8.2,
        startTime: 10_000,
      },
      {
        isActive: true,
        nowMs: 13_500,
      },
    ),
    8.2,
  );
});

test('isFallbackExecution does not flag a custom provider when requested route and model match', () => {
  assert.equal(
    isFallbackExecution(
      {
        requested_model: 'gpt-5.5',
        requested_provider_route: 'custom',
        model: 'gpt-5.5',
        provider_route: 'custom',
        fallback_used: false,
      },
      { model: 'gpt-5.5', providerRoute: 'custom' },
    ),
    false,
  );
});

test('isFallbackExecution flags real provider fallback', () => {
  assert.equal(
    isFallbackExecution(
      {
        requested_model: 'gpt-5.5',
        requested_provider_route: 'custom',
        model: 'gpt-5.4',
        provider_route: 'cloud',
        fallback_used: true,
      },
      { model: 'gpt-5.5', providerRoute: 'custom' },
    ),
    true,
  );
});

test('getActionPlanRoundStats returns the matching request section', () => {
  const stats = {
    requests: [
      { section: 'analysis', total_tokens: 15 },
      { section: 'plan', total_tokens: 28 },
    ],
  };

  assert.deepEqual(getActionPlanRoundStats(stats, 'plan'), { section: 'plan', total_tokens: 28 });
  assert.equal(getActionPlanRoundStats(stats, 'missing'), null);
});

test('getActionPlanRoundStats treats completed calls without usage as unrecorded instead of zero', () => {
  const stats = {
    requests: [
      {
        section: 'analysis',
        duration: 266.0,
        prompt_tokens: 0,
        completion_tokens: 0,
        total_tokens: 0,
        prompt_cache_hit_tokens: 0,
        prompt_cache_miss_tokens: 0,
        prompt_cache_hit_rate: null,
        completion_tokens_per_second: 0,
        total_tokens_per_second: 0,
      },
    ],
  };

  const roundStats = getActionPlanRoundStats(stats, 'analysis');

  assert.equal(roundStats.usage_recorded, false);
  assert.equal(roundStats.total_tokens, null);
  assert.equal(roundStats.prompt_cache_hit_tokens, null);
  assert.equal(roundStats.completion_tokens_per_second, null);
});

test('formatActionPlanTokenBreakdown includes total, prompt, and completion tokens', () => {
  assert.equal(
    formatActionPlanTokenBreakdown({
      prompt_tokens: 180000,
      completion_tokens: 57100,
      total_tokens: 237100,
    }),
    '237.1k (P 180.0k / C 57.1k)',
  );
});

test('formatActionPlanTokenBreakdown and cache breakdown do not render fake zeroes for unrecorded usage', () => {
  const stats = {
    usage_recorded: false,
    prompt_tokens: null,
    completion_tokens: null,
    total_tokens: null,
    prompt_cache_hit_tokens: null,
    prompt_cache_miss_tokens: null,
    prompt_cache_hit_rate: null,
  };

  assert.equal(formatActionPlanTokenBreakdown(stats), '-');
  assert.equal(formatActionPlanCacheBreakdown(stats), null);
});

test('formatActionPlanCacheBreakdown does not turn a null cache rate into 0 percent', () => {
  assert.equal(
    formatActionPlanCacheBreakdown({
      prompt_cache_hit_tokens: 0,
      prompt_cache_miss_tokens: 225614,
      prompt_cache_hit_rate: null,
    }),
    'H 0 / M 225.6k',
  );
});

test('formatThinkingTitleWithDuration appends elapsed seconds and reasoning tokens', () => {
  assert.equal(formatThinkingTitleWithDuration('推理过程', 12.34, 1280), '推理过程（12.3s，1.3k Token）');
  assert.equal(formatThinkingTitleWithDuration('Reasoning', 12.34, 1280), 'Reasoning (12.3s, 1.3k tokens)');
  assert.equal(formatThinkingTitleWithDuration('推理过程', 0, 1280), '推理过程（1.3k Token）');
  assert.equal(formatThinkingTitleWithDuration('推理过程', 0, 0), '推理过程');
});

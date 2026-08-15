import test from 'node:test';
import assert from 'node:assert/strict';

import * as actionPlanStats from './actionPlanStats.js';

import {
  computeDisplayedDurationSeconds,
  formatActionPlanCacheBreakdown,
  formatActionPlanSpeed,
  formatActionPlanTokenBreakdown,
  formatThinkingTitleWithDuration,
  formatPoweredByLabel,
  formatReasoningEffortLabel,
  getActionPlanPromptContextWarning,
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

test('getActionPlanPromptContextWarning ignores aggregate prompt totals when request prompts fit', () => {
  const warning = getActionPlanPromptContextWarning({
    prompt_tokens: 345800,
    prompt_token_limit: 250000,
    prompt_token_limit_exceeded: true,
    prompt_context_warning: {
      limit: 250000,
      prompt_tokens: 345800,
      observed_prompt_tokens: 345800,
    },
    requests: [
      {
        section: 'analysis',
        prompt_tokens: 166400,
        prompt_token_limit: 250000,
        prompt_token_limit_exceeded: false,
        prompt_context_warning: null,
      },
      {
        section: 'plan',
        prompt_tokens: 179400,
        prompt_token_limit: 250000,
        prompt_token_limit_exceeded: false,
        prompt_context_warning: null,
      },
    ],
  });

  assert.equal(warning, null);
});

test('getActionPlanPromptContextWarning reports the largest per-request prompt overflow', () => {
  const warning = getActionPlanPromptContextWarning({
    requests: [
      {
        section: 'analysis',
        prompt_tokens: 180000,
        prompt_token_limit: 250000,
        prompt_token_limit_exceeded: false,
      },
      {
        section: 'plan',
        prompt_tokens: 260793,
        prompt_token_limit: 250000,
        prompt_token_limit_exceeded: true,
        prompt_context_warning: {
          limit: 250000,
          prompt_tokens: 260793,
          observed_prompt_tokens: 260793,
        },
      },
    ],
  });

  assert.deepEqual(warning, {
    limit: 250000,
    observedPromptTokens: 260793,
    estimated: false,
  });
});

test('getActionPlanRoundStats treats completed calls without usage as unrecorded instead of zero', () => {
  const stats = {
    requests: [
      {
        section: 'analysis',
        duration: 266.0,
        usage_recorded: true,
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

test('getActionPlanRoundNotice separates incomplete streams from unavailable usage', () => {
  assert.equal(typeof actionPlanStats.getActionPlanRoundNotice, 'function');
  const getNotice = actionPlanStats.getActionPlanRoundNotice;

  assert.equal(getNotice({
    requests: [{
      section: 'analysis',
      duration: 12,
      stream_completed: false,
      usage_recorded: false,
      prompt_tokens: null,
      completion_tokens: null,
      total_tokens: null,
    }],
  }, 'analysis', 'partial body'), 'incomplete');

  assert.equal(getNotice({
    requests: [{
      section: 'analysis',
      duration: 12,
      stream_completed: true,
      stream_terminal_event: 'done',
      finish_reason: 'stop',
      usage_recorded: false,
      prompt_tokens: null,
      completion_tokens: null,
      total_tokens: null,
    }],
  }, 'analysis', 'complete body'), 'usage_unavailable');

  assert.equal(getNotice({
    requests: [{
      section: 'analysis',
      duration: 12,
      usage_recorded: true,
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
    }],
  }, 'analysis', 'legacy complete body'), 'usage_unavailable');

  assert.equal(getNotice({
    requests: [{
      section: 'analysis',
      duration: 12,
      stream_completed: true,
      finish_reason: 'stop',
      usage_recorded: true,
      prompt_tokens: 8,
      completion_tokens: 2,
      total_tokens: 10,
    }],
  }, 'analysis', 'complete body'), null);

  assert.equal(getNotice({
    requests: [{
      section: 'analysis',
      duration: 12,
      stream_completed: true,
      finish_reason: 'length',
      usage_recorded: true,
      prompt_tokens: 8,
      completion_tokens: 2,
      total_tokens: 10,
    }],
  }, 'analysis', 'truncated body'), 'incomplete');

  assert.equal(getNotice({
    requests: [{ section: 'analysis', duration: 12, stream_completed: false }],
  }, 'analysis', ''), null);
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

test('formatActionPlanSpeed does not render a fake zero for incomplete aggregate usage', () => {
  assert.equal(formatActionPlanSpeed({
    usage_recorded: false,
    usage_complete: false,
    speed: null,
  }), '-');
  assert.equal(formatActionPlanSpeed({
    usage_recorded: true,
    usage_complete: true,
    completion_tokens: 5,
    speed: '2.50 tokens/s',
  }), '2.50 tokens/s');
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

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  computeDisplayedDurationSeconds,
  formatActionPlanTokenBreakdown,
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

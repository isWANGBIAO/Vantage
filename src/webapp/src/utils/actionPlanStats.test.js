import test from 'node:test';
import assert from 'node:assert/strict';

import {
  computeDisplayedDurationSeconds,
  formatPoweredByLabel,
  formatReasoningEffortLabel,
} from './actionPlanStats.js';

test('formatPoweredByLabel prefers model and provider display name', () => {
  assert.equal(
    formatPoweredByLabel({
      model: 'gpt-5.2',
      provider_route: 'cliproxyapi_primary',
    }),
    'gpt-5.2 · CLIProxyAPI',
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

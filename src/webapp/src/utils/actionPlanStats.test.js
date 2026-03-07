import test from 'node:test';
import assert from 'node:assert/strict';

import {
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

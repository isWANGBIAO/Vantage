import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const onboardingShellSource = readFileSync(new URL('./OnboardingShell.jsx', import.meta.url), 'utf8');

test('OnboardingShell defines the four first-run placeholder steps', () => {
  assert.ok(onboardingShellSource.includes('const STEP_ORDER ='));
  assert.ok(onboardingShellSource.includes("'welcome'"));
  assert.ok(onboardingShellSource.includes("'provider'"));
  assert.ok(onboardingShellSource.includes("'migration'"));
  assert.ok(onboardingShellSource.includes("'complete'"));
});

test('OnboardingShell allows skipping chat setup and opening the app preview', () => {
  assert.ok(onboardingShellSource.includes('Skip Chat Setup'));
  assert.ok(onboardingShellSource.includes('Open App Preview'));
  assert.ok(onboardingShellSource.includes('Continue'));
  assert.ok(onboardingShellSource.includes('Back'));
});

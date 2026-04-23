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
  assert.ok(onboardingShellSource.includes('Finish Setup'));
  assert.ok(onboardingShellSource.includes('Continue'));
  assert.ok(onboardingShellSource.includes('Back'));
});

test('OnboardingShell collects provider fields and legacy import controls before finishing', () => {
  assert.ok(onboardingShellSource.includes('Provider Route'));
  assert.ok(onboardingShellSource.includes('API Base URL'));
  assert.ok(onboardingShellSource.includes('API Key'));
  assert.ok(onboardingShellSource.includes('Model'));
  assert.ok(onboardingShellSource.includes('Import existing history into the packaged app data directory'));
  assert.ok(onboardingShellSource.includes('Choose Folder'));
});

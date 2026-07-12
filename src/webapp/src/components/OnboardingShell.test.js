import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const onboardingShellSource = readFileSync(new URL('./OnboardingShell.jsx', import.meta.url), 'utf8');
const appSource = readFileSync(new URL('../App.jsx', import.meta.url), 'utf8');
const displayCopySource = readFileSync(new URL('../utils/displayCopy.js', import.meta.url), 'utf8');

test('OnboardingShell defines the four first-run placeholder steps', () => {
  assert.ok(onboardingShellSource.includes('const STEP_ORDER ='));
  assert.ok(onboardingShellSource.includes("'welcome'"));
  assert.ok(onboardingShellSource.includes("'provider'"));
  assert.ok(onboardingShellSource.includes("'migration'"));
  assert.ok(onboardingShellSource.includes("'complete'"));
});

test('OnboardingShell allows skipping chat setup and opening the app preview', () => {
  assert.ok(onboardingShellSource.includes("t('onboarding.button.skip_chat')"));
  assert.ok(onboardingShellSource.includes("t('onboarding.button.finish')"));
  assert.ok(onboardingShellSource.includes("t('onboarding.button.continue')"));
  assert.ok(onboardingShellSource.includes("t('onboarding.button.back')"));
});

test('OnboardingShell exposes display language controls on first run', () => {
  assert.ok(onboardingShellSource.includes('displayLanguage'));
  assert.ok(onboardingShellSource.includes('onDisplayLanguageChange'));
  assert.ok(onboardingShellSource.includes('Follow System'));
  assert.ok(onboardingShellSource.includes('Simplified Chinese'));
  assert.ok(onboardingShellSource.includes('English'));
});

test('OnboardingShell collects provider fields and legacy import controls before finishing', () => {
  assert.ok(onboardingShellSource.includes("t('onboarding.field.provider_route')"));
  assert.ok(onboardingShellSource.includes("t('onboarding.field.api_base_url')"));
  assert.ok(onboardingShellSource.includes("t('onboarding.field.api_key')"));
  assert.ok(onboardingShellSource.includes("t('onboarding.field.model')"));
  assert.ok(onboardingShellSource.includes("t('onboarding.field.import_legacy')"));
  assert.ok(onboardingShellSource.includes("t('onboarding.button.choose_folder')"));
});

test('first-run and footer copy omit the removed provider', () => {
  const removedProvider = ['gemi', 'ni'].join('');
  assert.equal(onboardingShellSource.toLowerCase().includes(removedProvider), false);
  assert.equal(appSource.toLowerCase().includes(removedProvider), false);
  assert.equal(displayCopySource.toLowerCase().includes(removedProvider), false);
});

test('OnboardingShell keeps the first-run window draggable under hidden native chrome', () => {
  assert.ok(onboardingShellSource.includes('app-layout--electron'));
  assert.ok(onboardingShellSource.includes('window.electronAPI'));
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('./App.jsx', import.meta.url), 'utf8');

test('App passes the current theme into chart-heavy screens', () => {
  assert.ok(appSource.includes('<ExpenseSheet theme={theme} />'));
  assert.ok(appSource.includes('<Plots theme={theme} />'));
});

test('App code-splits non-default tabs but still preloads them after startup', () => {
  assert.ok(appSource.includes('function lazyWithPreload'));
  assert.ok(appSource.includes('lazyWithPreload(() => import('));
  assert.ok(appSource.includes('backgroundTabsReady'));
  assert.ok(appSource.includes('Promise.all(BACKGROUND_TAB_COMPONENTS.map('));
  assert.ok(appSource.includes('.preload()'));
  assert.ok(appSource.includes('<Suspense fallback={null}>'));
  assert.equal(appSource.includes("import Dashboard from './components/Dashboard'"), false);
});

test('App keeps the global footer off full-height tabs including system logs', () => {
  assert.ok(appSource.includes("activeTab !== 'system logs'"));
});

test('App keeps dashboard prewarm mounted but passes visibility into Dashboard', () => {
  assert.ok(appSource.includes("<Dashboard isVisible={activeTab === 'dashboard'} />"));
});

test('App keeps face-history prewarm mounted but passes visibility into FaceHistory', () => {
  assert.ok(appSource.includes("<FaceHistory isVisible={activeTab === 'face history'} />"));
});

test('App gates the workspace behind onboarding when setup is incomplete', () => {
  assert.ok(appSource.includes('loadOnboardingState'));
  assert.ok(appSource.includes('<OnboardingShell'));
  assert.ok(appSource.includes('showOnboardingShell'));
  assert.ok(appSource.includes('initialMigrationCompleted={onboardingState.migrationCompleted}'));
});

test('App submits onboarding completion through the Electron bridge helpers', () => {
  assert.ok(appSource.includes('completeOnboardingSetup'));
  assert.ok(appSource.includes('pickLegacyRoot'));
  assert.ok(appSource.includes('handleCompleteOnboarding'));
});

test('App wires the display language provider and header switcher into the shell', () => {
  assert.ok(appSource.includes('DisplayLanguageProvider'));
  assert.ok(appSource.includes('useDisplayLanguage'));
  assert.ok(appSource.includes('app-language-select'));
  assert.ok(appSource.includes('displayLanguage'));
});

test('App only reapplies onboarding language when the saved onboarding value changes', () => {
  assert.ok(appSource.includes('lastAppliedOnboardingLanguageRef'));
  assert.ok(appSource.includes('lastAppliedOnboardingLanguageRef.current === onboardingState.displayLanguage'));
  assert.ok(appSource.includes('lastAppliedOnboardingLanguageRef.current = onboardingState.displayLanguage'));
});

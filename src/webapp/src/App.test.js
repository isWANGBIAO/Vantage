import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('./App.jsx', import.meta.url), 'utf8');

test('App passes the current theme into chart-heavy screens', () => {
  assert.ok(appSource.includes('<ExpenseSheet theme={theme} />'));
  assert.ok(appSource.includes('<Plots theme={theme} />'));
});

test('App code-splits and always preloads background tabs after settings load', () => {
  assert.ok(appSource.includes('function lazyWithPreload'));
  assert.ok(appSource.includes('lazyWithPreload(() => import('));
  assert.ok(appSource.includes('backgroundTabsReady'));
  assert.ok(appSource.includes('Promise.allSettled(BACKGROUND_TAB_COMPONENTS.map('));
  assert.ok(appSource.includes('.preload()'));
  assert.ok(appSource.includes('setBackgroundTabsReady(true)'));
  assert.ok(appSource.includes('const settingsReady = Boolean(settingsState);'));
  assert.ok(appSource.includes('}, [settingsReady]);'));
  assert.equal(appSource.includes('}, [settingsState]);'), false);
  assert.ok(appSource.includes('<Suspense fallback={null}>'));
  assert.equal(appSource.includes("import Dashboard from './components/Dashboard'"), false);
  assert.equal(appSource.includes('backgroundMode'), false);
  assert.equal(appSource.includes("'balanced'"), false);
  assert.equal(appSource.includes("'prewarm'"), false);
  assert.equal(appSource.includes("'power_saver'"), false);
});

test('App exposes Settings through a top-right gear without adding it to tab prewarm', () => {
  assert.ok(appSource.includes("const Settings = lazyWithPreload(() => import('./components/Settings'))"));
  assert.ok(appSource.includes("activeTab === 'settings'"));
  assert.ok(appSource.includes("t('app.nav.settings')"));
  assert.ok(appSource.includes('SettingsIcon'));
  assert.ok(appSource.includes('className="settings-entry-button"'));
  assert.equal(appSource.includes('theme-toggle settings-entry-button'), false);
  assert.ok(appSource.includes('<span>{t(\'app.nav.settings\')}</span>'));
  assert.equal(appSource.includes('BACKGROUND_TAB_COMPONENTS = [\n  Dashboard,\n  ProjectProgress,\n  ExpenseSheet,\n  Plots,\n  SystemLogs,\n  FaceHistory,\n  Settings'), false);
});

test('App persists the header theme toggle through formal settings', () => {
  assert.ok(appSource.includes('handleToggleTheme'));
  assert.ok(appSource.includes('saveSettingsState'));
  assert.ok(appSource.includes('displayLanguage,'));
  assert.ok(appSource.includes('theme: nextTheme'));
  assert.ok(appSource.includes('themeMode: nextTheme'));
});

test('App preserves voice provider settings when saving the header theme toggle', () => {
  assert.ok(appSource.includes('voiceBaseUrl: currentState.settings?.voiceBaseUrl'));
  assert.ok(appSource.includes('voiceApiKey: currentState.settings?.voiceApiKey'));
  assert.ok(appSource.includes('voiceModel: currentState.settings?.voiceModel'));
  assert.ok(appSource.includes('voiceProviderMode: currentState.settings?.voiceProviderMode'));
  assert.ok(appSource.includes('voiceModels: currentState.settings?.voiceModels'));
  assert.ok(appSource.includes('imageBaseUrl: currentState.settings?.imageBaseUrl'));
  assert.ok(appSource.includes('imageApiKey: currentState.settings?.imageApiKey'));
  assert.ok(appSource.includes('imageModel: currentState.settings?.imageModel'));
  assert.ok(appSource.includes('imageProviderMode: currentState.settings?.imageProviderMode'));
  assert.ok(appSource.includes('imageModels: currentState.settings?.imageModels'));
});

test('App renders the header theme toggle as a labelled pill instead of a blank circle', () => {
  assert.ok(appSource.includes('className="theme-toggle"'));
  assert.ok(appSource.includes("<span>{t(theme === 'dark' ? 'settings.general.theme_light' : 'settings.general.theme_dark')}</span>"));
});

test('App supports automatic theme mode driven by prefers-color-scheme', () => {
  assert.ok(appSource.includes('resolveSystemTheme'));
  assert.ok(appSource.includes('resolveEffectiveTheme'));
  assert.ok(appSource.includes("const [themeMode, setThemeMode]"));
  assert.ok(appSource.includes("window.matchMedia('(prefers-color-scheme: dark)'"));
  assert.ok(appSource.includes('currentThemeMode={themeMode}'));
});

test('App keeps the global footer off full-height tabs including system logs', () => {
  assert.ok(appSource.includes("activeTab !== 'system logs'"));
});

test('App keeps dashboard prewarm mounted but passes visibility into Dashboard', () => {
  assert.ok(appSource.includes("<Dashboard isVisible={activeTab === 'dashboard'} />"));
});

test('App passes visibility into SystemLogs so hidden panels do not poll logs', () => {
  assert.ok(appSource.includes("<SystemLogs isVisible={activeTab === 'system logs'} />"));
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

test('App initializes and syncs the active tab from the URL hash', () => {
  assert.ok(appSource.includes('const TAB_HASH_TO_KEY'));
  assert.ok(appSource.includes('function getTabKeyFromHash'));
  assert.ok(appSource.includes("useState(() => getTabKeyFromHash(window.location.hash) || 'action plan')"));
  assert.ok(appSource.includes("window.addEventListener('hashchange'"));
  assert.ok(appSource.includes('window.history.pushState'));
  assert.ok(appSource.includes('handleNavTabChange'));
});

test('App only reapplies onboarding language when the saved onboarding value changes', () => {
  assert.ok(appSource.includes('lastAppliedOnboardingLanguageRef'));
  assert.ok(appSource.includes('lastAppliedOnboardingLanguageRef.current === onboardingState.displayLanguage'));
  assert.ok(appSource.includes('lastAppliedOnboardingLanguageRef.current = onboardingState.displayLanguage'));
});

test('App header is configured as the draggable frameless window region', () => {
  const appCss = readFileSync(new URL('./App.css', import.meta.url), 'utf8');

  assert.ok(appSource.includes('app-layout--electron'));
  assert.ok(appSource.includes('setTitleBarTheme'));
  assert.match(appCss, /\.app-layout--electron \.app-header\s*{[\s\S]*-webkit-app-region:\s*drag;/);
  assert.match(appCss, /\.app-layout--electron \.app-header-actions\s*{[\s\S]*-webkit-app-region:\s*no-drag;/);
  assert.match(appCss, /\.app-layout--electron \.app-brand\s*{[\s\S]*-webkit-app-region:\s*drag;/);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { getOnboardingState } = require('./onboardingConfig.cjs');

test('getOnboardingState defaults to incomplete when settings file is missing', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'vantage-onboarding-'));
  const runtimePaths = {
    configDir: path.join(root, 'config'),
  };

  const state = getOnboardingState({ runtimePaths });

  assert.deepEqual(state, {
    completed: false,
    launchAtLogin: false,
  });
});

test('getOnboardingState reads onboarding flags from settings.json', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'vantage-onboarding-'));
  const configDir = path.join(root, 'config');
  mkdirSync(configDir, { recursive: true });
  writeFileSync(
    path.join(configDir, 'settings.json'),
    JSON.stringify({
      version: 1,
      onboarding_completed: true,
      launch_at_login: true,
    }),
    'utf8',
  );

  const state = getOnboardingState({
    runtimePaths: {
      configDir,
    },
  });

  assert.deepEqual(state, {
    completed: true,
    launchAtLogin: true,
  });
});

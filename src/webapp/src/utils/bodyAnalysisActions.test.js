import test from 'node:test';
import assert from 'node:assert/strict';
import { createPlatformAdapter } from './platformAdapter.js';
import { saveSettingsState } from './settingsState.js';
import {
  chooseAndSaveDirectory,
  environmentGuidance,
  refreshPublishedReport,
  requestOptionalInstall,
  shouldMountFaceHistory,
} from './bodyAnalysisActions.js';

test('folder picker persists only its selected JSON setting through the canonical backend', async () => {
  const requests = [];
  const platform = createPlatformAdapter({
    descriptor: { kind: 'electron' },
    pickBodyAnalysisDirectory: async (kind) => {
      assert.equal(kind, 'leg');
      return { path: 'chosen-leg-folder' };
    },
    requestConfiguration: async (method, path, body) => {
      requests.push({ method, path, body });
      return { settings: { body_analysis_leg_dir: body.body_analysis_leg_dir } };
    },
  });
  const state = await chooseAndSaveDirectory('leg', {
    pick: platform.paths.pickBodyAnalysisDirectory,
    save: (fields) => saveSettingsState(fields, platform),
  });
  assert.deepEqual(requests, [{ method: 'PUT', path: '/api/v1/settings', body: { body_analysis_leg_dir: 'chosen-leg-folder' } }]);
  assert.equal(state.settings.bodyAnalysisLegDir, 'chosen-leg-folder');
});

test('cancelled folder picker never mutates settings', async () => {
  let saves = 0;
  const result = await chooseAndSaveDirectory('scalp', {
    pick: async () => ({ path: null }),
    save: async () => { saves += 1; },
  });
  assert.equal(result, null);
  assert.equal(saves, 0);
});

test('environment guidance distinguishes model, Python 3.11, CUDA, and optional packages', () => {
  const cases = [
    [['model'], 'missing_model', 'body_analysis.missing_model', false],
    [['python'], 'missing_python', 'body_analysis.missing_python', false],
    [['cuda'], 'cuda_unavailable', 'body_analysis.missing_cuda', false],
    [['dependencies'], 'missing_dependencies', 'body_analysis.environment_missing', true],
  ];
  for (const [missing, reason, messageKey, canInstall] of cases) {
    assert.deepEqual(environmentGuidance({ status: 'missing_environment', environment: { missing, reason } }), { messageKey, canInstall });
  }
  assert.equal(environmentGuidance({ status: 'ready' }), null);
  assert.deepEqual(environmentGuidance({ status: 'missing_environment', environment: { reason: 'missing_dependencies', missing: [] } }), { messageKey: 'body_analysis.environment_missing', canInstall: true });
  assert.deepEqual(environmentGuidance({ status: 'missing_environment', environment: { reason: 'unknown', missing: ['dependencies', 'cuda'] } }), { messageKey: 'body_analysis.missing_cuda', canInstall: false });
});

test('install is explicit and refuses non-dependency problems', async () => {
  let installs = 0;
  const post = async () => { installs += 1; return { status: 'installing' }; };
  assert.equal(await requestOptionalInstall({ status: 'missing_environment', environment: { missing: ['python'] } }, post), false);
  assert.equal(installs, 0);
  assert.equal(await requestOptionalInstall({ status: 'missing_environment', environment: { missing: ['dependencies'] } }, post), true);
  assert.equal(installs, 1);
});

test('failed refresh keeps the last complete report visible', async () => {
  const previous = { schema_version: 1, complete: true, leg: { records: [] } };
  const result = await refreshPublishedReport(previous, {
    readStatus: async () => ({ status: 'failed', last_report_available: true }),
    readReport: async () => { throw new Error('temporary failure'); },
  });
  assert.equal(result.report, previous);
  assert.equal(result.status.status, 'failed');
  const unavailable = await refreshPublishedReport(previous, {
    readStatus: async () => { throw new Error('private path must not leak'); },
    readReport: async () => { throw new Error('should not run'); },
  });
  assert.equal(unavailable.report, previous);
  assert.equal(unavailable.error, 'status_unavailable');
});

test('FaceHistory mounts only on the dark-circles subpage', () => {
  assert.equal(shouldMountFaceHistory('dark-circles'), true);
  assert.equal(shouldMountFaceHistory('leg'), false);
  assert.equal(shouldMountFaceHistory('scalp'), false);
});

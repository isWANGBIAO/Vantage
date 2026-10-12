import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('./BodyAnalysis.jsx', import.meta.url), 'utf8');
const viewModelSource = readFileSync(new URL('../utils/bodyAnalysisViewModel.js', import.meta.url), 'utf8');
const actionsSource = readFileSync(new URL('../utils/bodyAnalysisActions.js', import.meta.url), 'utf8');

test('body analysis contains dark-circle, leg-hair, and scalp subpages', () => {
  assert.match(source, /FaceHistory/);
  assert.match(source, /body_analysis\.tab\.dark_circles/);
  assert.match(source, /body_analysis\.tab\.leg/);
  assert.match(source, /body_analysis\.tab\.scalp/);
});

test('body analysis uses backend status and structured report, not report HTML', () => {
  assert.match(source, /\/api\/v1\/body-analysis\/status/);
  assert.match(source, /\/api\/v1\/body-analysis\/report/);
  assert.match(viewModelSource, /\/api\/v1\/body-analysis\/assets\//);
  assert.equal(source.includes('dangerouslySetInnerHTML'), false);
  assert.equal(source.includes('<iframe'), false);
});

test('optional environment install is user-triggered and last report remains visible', () => {
  assert.match(source, /body_analysis\.install/);
  assert.match(source, /runAction\('install'\)/);
  assert.match(actionsSource, /last_report_available/);
  assert.match(source, /body_analysis\.retry/);
  assert.match(source, /body_analysis\.quality/);
  assert.match(viewModelSource, /trend_eligible/);
});

test('report renders inspectable masks and only eligible trend records', () => {
  assert.match(source, /visibleTrend\(report, kind\)/);
  assert.match(source, /trend\.map/);
  assert.match(source, /texture_mask_path/);
  assert.match(source, /line_mask_path/);
  assert.match(source, /scalp_candidate_mask_path/);
  assert.match(source, /body_analysis\.leg_proxy_notice/);
  assert.match(source, /body_analysis\.no_verified_scalp_trend/);
});

test('component delegates folder, report, and install transitions to tested behavior helpers', () => {
  assert.match(source, /chooseAndSaveDirectory\(/);
  assert.match(actionsSource, /refreshPublishedReport\(/);
  assert.match(source, /requestOptionalInstall\(/);
  assert.match(source, /shouldMountFaceHistory\(subtab\)/);
  assert.match(source, /environmentGuidance\(status\)/);
  assert.match(source, /createBodyAnalysisPoller\(/);
  assert.match(source, /poller\.dispose\(\)/);
});

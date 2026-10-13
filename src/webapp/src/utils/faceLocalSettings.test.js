import test from 'node:test';
import assert from 'node:assert/strict';

let helpers = {};
try {
  helpers = await import('./faceLocalSettings.js');
} catch (error) {
  if (error.code !== 'ERR_MODULE_NOT_FOUND') throw error;
}

test('local face settings only submit the five shared settings fields', () => {
  assert.equal(typeof helpers.normalizeFaceLocalSettings, 'function');
  assert.deepEqual(helpers.normalizeFaceLocalSettings({
    face_analysis_method: 'sam3', face_analysis_python: ' python ',
    face_analysis_sam3_python: ' gpu-python ',
    face_analysis_onnx_model: ' model ', face_analysis_sam3_model_dir: ' checkpoint ',
    body_analysis_enabled: true,
  }), {
    face_analysis_method: 'sam3', face_analysis_python: 'python',
    face_analysis_sam3_python: 'gpu-python',
    face_analysis_onnx_model: 'model', face_analysis_sam3_model_dir: 'checkpoint',
  });
});

test('local face settings have no machine paths or automatic fallback method', () => {
  assert.equal(typeof helpers.normalizeFaceLocalSettings, 'function');
  assert.deepEqual(helpers.normalizeFaceLocalSettings({}), {
    face_analysis_method: 'onnx', face_analysis_python: '',
    face_analysis_sam3_python: '',
    face_analysis_onnx_model: '', face_analysis_sam3_model_dir: '',
  });
});

test('sampling preview only accepts local face overlay endpoint URLs', () => {
  assert.equal(typeof helpers.getFaceOverlayUrl, 'function');
  assert.equal(helpers.getFaceOverlayUrl('/api/v1/face/overlay?profile=abc'), '/api/v1/face/overlay?profile=abc');
  for (const url of ['https://example.com/photo', 'file:///photo', 'javascript:alert(1)', '//example.com/photo', '/api/v1/face/../settings']) {
    assert.equal(helpers.getFaceOverlayUrl(url), '');
  }
});

test('missing local scores are not displayed as zero', () => {
  assert.equal(typeof helpers.formatFaceScore, 'function');
  for (const value of [null, undefined, '', NaN, Infinity]) assert.equal(helpers.formatFaceScore(value), '--');
  assert.equal(helpers.formatFaceScore(0), '0.00');
  assert.equal(helpers.formatFaceScore(12.345), '12.35');
});

test('skip reasons map to readable localized diagnostics', () => {
  assert.equal(typeof helpers.faceSkipReasonKey, 'function');
  assert.equal(helpers.faceSkipReasonKey('Blurry(15)'), 'face_local.skip.blurry');
  assert.equal(helpers.faceSkipReasonKey('eyes_missing'), 'face_local.skip.eyes');
  assert.equal(helpers.faceSkipReasonKey('cheek_skin_missing'), 'face_local.skip.cheek');
  assert.equal(helpers.faceSkipReasonKey('UnstablePose'), 'face_local.skip.pose');
  assert.equal(helpers.faceSkipReasonKey('UnknownIssue'), 'face_local.skip.other');
});

const PATH_FIELDS = ['face_analysis_python', 'face_analysis_sam3_python', 'face_analysis_onnx_model', 'face_analysis_sam3_model_dir'];

export function normalizeFaceLocalSettings(settings = {}) {
  return {
    face_analysis_method: settings.face_analysis_method === 'sam3' ? 'sam3' : 'onnx',
    ...Object.fromEntries(PATH_FIELDS.map((field) => [field, typeof settings[field] === 'string' ? settings[field].trim() : ''])),
  };
}

export function getFaceOverlayUrl(value) {
  if (typeof value !== 'string' || !/^\/api\/v1\/face\/overlay(?:\?|$)/.test(value)) return '';
  return value;
}

export function formatFaceScore(value) {
  if (value === null || value === undefined || value === '') return '--';
  return Number.isFinite(Number(value)) ? Number(value).toFixed(2) : '--';
}

const SKIP_REASON_KEYS = {
  eyes_missing: 'eyes', brows_missing: 'brows', brow_eye_gap_missing: 'gap',
  under_eye_skin_missing: 'under_eye', cheek_skin_missing: 'cheek',
  invalid_parsing_map: 'parsing', ParsingSizeMismatch: 'parsing', ReadError: 'read',
  NoFace: 'face', FaceMaskTooSmall: 'skin', ExtremeExposure: 'exposure',
  UnderEyePixelsTooSmall: 'under_eye', UnstableEyeArea: 'eyes',
  UnstablePose: 'pose', UnstableFaceBox: 'pose', UnstableLeftRightGap: 'asymmetry',
  UnstableBrightness: 'lighting', UnstableLighting: 'lighting',
};

export function faceSkipReasonKey(reason) {
  const category = String(reason).startsWith('Blurry(') ? 'blurry' : (SKIP_REASON_KEYS[reason] || 'other');
  return `face_local.skip.${category}`;
}

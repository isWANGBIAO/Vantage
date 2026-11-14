export const CLOTHING_MEASUREMENTS = Object.freeze(['length_cm', 'chest_cm', 'chest_width_cm', 'shoulder_cm', 'sleeve_cm', 'measurement_tolerance_cm']);
export const CLOTHING_FEEDBACK_FIELDS = Object.freeze(['trial_date', 'feedback_scope', 'shoulder_feedback', 'sleeve_feedback', 'length_feedback', 'chest_feedback', 'mobility_feedback', 'overall_feedback', 'layering', 'notes']);
const TEXT_FIELDS = ['garment', 'brand', 'style_code', 'category', 'size', 'component', 'length_basis', 'sleeve_basis', 'measurement_source', ...CLOTHING_FEEDBACK_FIELDS];
export function emptyClothingDraft() {
  return Object.fromEntries([
    ...TEXT_FIELDS.map(key => [key, '']), ...CLOTHING_MEASUREMENTS.map(key => [key, null]),
    ['row', null], ['component', '未知'], ['category', '未知'], ['feedback_scope', '未知'],
    ['length_basis', '未知'], ['sleeve_basis', '未知'], ['measurement_source', '人工录入'], ['record_kind', 'garment'], ['warnings', []],
  ]);
}
export function clothingDraft(record = {}) {
  const result = emptyClothingDraft();
  for (const key of TEXT_FIELDS) if (typeof record[key] === 'string') result[key] = record[key];
  for (const key of CLOTHING_MEASUREMENTS) if (typeof record[key] === 'number' && Number.isFinite(record[key])) result[key] = record[key];
  if (Number.isInteger(record.row) && record.row >= 2) result.row = record.row;
  if (['garment', 'body', 'unclassified'].includes(record.record_kind)) result.record_kind = record.record_kind;
  result.warnings = Array.isArray(record.warnings) ? record.warnings.filter(v => typeof v === 'string') : [];
  return result;
}
export function editClothingDraft(state, key, value) {
  return { ...state, draft: { ...state.draft, [key]: value }, confirmed: false, dirty: true, comparison: null };
}
export function newClothingCandidate(record) {
  const next = clothingDraft(record);
  for (const key of CLOTHING_FEEDBACK_FIELDS) next[key] = key === 'feedback_scope' ? '未知' : '';
  return { ...next, row: null, record_kind: 'garment', warnings: [] };
}
export function clothingPayload(draft) {
  const result = clothingDraft(draft);
  for (const key of TEXT_FIELDS) result[key] = typeof draft[key] === 'string' ? draft[key].trim() : result[key];
  for (const key of CLOTHING_MEASUREMENTS) {
    const value = draft[key];
    if (value === '' || value == null) { result[key] = null; continue; }
    if (typeof value === 'boolean' || !/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(String(value).trim())) throw new TypeError(`Invalid clothing measurement: ${key}`);
    const number = Number(value);
    const minimum = key === 'measurement_tolerance_cm' ? 0 : Number.MIN_VALUE;
    const maximum = key === 'measurement_tolerance_cm' ? 20 : 400;
    if (!Number.isFinite(number) || number < minimum || number > maximum) throw new TypeError(`Invalid clothing measurement: ${key}`);
    result[key] = number;
  }
  if (!result.garment || result.record_kind !== 'garment') throw new TypeError('A garment record is required');
  delete result.warnings;
  delete result.record_kind;
  return result;
}
export function clothingCanSubmit(draft, confirmed, revision, busy, uncertain = false) {
  if (!confirmed || !revision || busy || uncertain) return false;
  try { clothingPayload(draft); return true; } catch { return false; }
}
export function clothingEvidenceNotice(record, english = false) {
  if (record.feedback_scope === '整件' && record.component !== '整件') return english
    ? 'Feedback describes the whole garment, not a separate shell or liner fitting.'
    : '反馈针对整件试穿，不能据此认定外壳或内胆单独合适。';
  if (!record.feedback_scope || record.feedback_scope === '未知') return english ? 'Fitting scope is unknown.' : '试穿反馈针对的部件尚未确认。';
  return '';
}
export function clothingErrorKind(error) {
  if (error?.name === 'AbortError') return 'cancelled';
  if (error?.status === 409 || error?.status === 423) return 'conflict';
  if (error?.status === 413) return 'image_large';
  if (error?.status === 422 || error instanceof TypeError) return 'invalid';
  if (error?.status === 503) return 'unavailable';
  return 'failed';
}
export function clothingNumber(value, empty = '—') {
  return typeof value === 'number' && Number.isFinite(value) ? String(Math.round(value * 100) / 100) : empty;
}

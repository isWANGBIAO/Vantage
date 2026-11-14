import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { clothingCanSubmit, clothingDraft, clothingErrorKind, clothingEvidenceNotice, clothingNumber, clothingPayload, editClothingDraft, emptyClothingDraft, newClothingCandidate } from './clothingFit.js';

test('clothing measurements preserve missing values and reject zero, NaN and coercion', () => {
  const draft = { ...emptyClothingDraft(), garment: 'Example coat', length_cm: '72.5', chest_cm: '' };
  assert.equal(clothingPayload(draft).length_cm, 72.5);
  assert.equal(clothingPayload(draft).chest_cm, null);
  assert.equal(clothingPayload({ ...draft, measurement_tolerance_cm: 0 }).measurement_tolerance_cm, 0);
  for (const value of [0, -1, NaN, Infinity, 'NaN', '72cm', true, '0x30', '']) {
    if (value === '') continue;
    assert.throws(() => clothingPayload({ ...draft, length_cm: value }), TypeError);
  }
  assert.throws(() => clothingPayload({ ...draft, measurement_tolerance_cm: 21 }), TypeError);
  assert.equal(clothingNumber(null), '—');
  assert.equal(clothingNumber(NaN), '—');
  assert.equal(clothingNumber(0), '0');
});
test('every field edit invalidates confirmation and stale comparison', () => {
  const state = { draft: { ...emptyClothingDraft(), garment: 'Example' }, confirmed: true, dirty: false, comparison: { summary: 'old' } };
  const next = editClothingDraft(state, 'brand', 'New brand');
  assert.equal(next.confirmed, false); assert.equal(next.dirty, true); assert.equal(next.comparison, null);
  assert.equal(state.draft.brand, '');
});
test('submissions require reviewed valid record, source revision and no pending or uncertain write', () => {
  const draft = { ...emptyClothingDraft(), garment: 'Example' };
  assert.equal(clothingCanSubmit(draft, true, 'revision', '', false), true);
  assert.equal(clothingCanSubmit(draft, false, 'revision', '', false), false);
  assert.equal(clothingCanSubmit(draft, true, null, '', false), false);
  assert.equal(clothingCanSubmit(draft, true, 'revision', 'save', false), false);
  assert.equal(clothingCanSubmit(draft, true, 'revision', '', true), false);
  assert.equal(clothingCanSubmit({ ...draft, record_kind: 'body' }, true, 'revision', '', false), false);
});
test('copying a historical measurement to a new candidate clears old fitting claims', () => {
  const source = clothingDraft({ garment: 'Example', row: 12, trial_date: '2020-01-01', shoulder_feedback: '合适', overall_feedback: '合适', notes: 'old trial' });
  const next = newClothingCandidate(source);
  assert.equal(next.row, null); assert.equal(next.trial_date, ''); assert.equal(next.shoulder_feedback, ''); assert.equal(next.overall_feedback, ''); assert.equal(next.notes, '');
  assert.equal(source.row, 12);
});
test('whole-garment claims remain distinct from shell and liner evidence', () => {
  assert.match(clothingEvidenceNotice({ component: '外壳', feedback_scope: '整件' }), /不能据此认定/);
  assert.match(clothingEvidenceNotice({ component: '内胆', feedback_scope: '整件' }, true), /not a separate/);
  assert.equal(clothingEvidenceNotice({ component: '整件', feedback_scope: '整件' }), '');
  assert.match(clothingEvidenceNotice({}), /尚未确认/);
});
test('UI error classification does not reveal private backend errors', () => {
  assert.equal(clothingErrorKind({ status: 409, message: 'private path' }), 'conflict');
  assert.equal(clothingErrorKind({ status: 413 }), 'image_large');
  assert.equal(clothingErrorKind({ status: 503 }), 'unavailable');
  assert.equal(clothingErrorKind({ status: 422 }), 'invalid');
  assert.equal(clothingErrorKind({ name: 'AbortError' }), 'cancelled');
  assert.equal(clothingErrorKind(new Error('private credential')), 'failed');
});

test('screenshot previews and extraction results stay bound to the same selection', () => {
  const component = readFileSync(new URL('../components/ClothingFit.jsx', import.meta.url), 'utf8');
  assert.match(component, /const sequence = \+\+imageSequence\.current;\s*setImage\(null\); setExtractions\(\[\]\);/);
  assert.match(component, /signal\.aborted \|\| sequence !== imageSequence\.current/);
  assert.match(component, /provider_route: source\.vision\.provider_route, model: source\.vision\.model/);
  assert.match(component, /await response\.arrayBuffer\(\)/);
});

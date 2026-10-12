import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveLegacyTabHash } from './appNavigation.js';

test('old face-history links open the Body Analysis dark-circles entry', () => {
  assert.equal(resolveLegacyTabHash('#face-history'), 'body-analysis');
  assert.equal(resolveLegacyTabHash('#FACE-HISTORY'), 'body-analysis');
  assert.equal(resolveLegacyTabHash('#unknown'), null);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { detectSystemLogSeverity, resolveSystemLogColor } from './systemLogSeverity.js';

test('system log severity catches uppercase warning and error prefixes', () => {
  assert.equal(detectSystemLogSeverity('WARNING: camera reconnect pending'), 'warning');
  assert.equal(detectSystemLogSeverity('ERROR: backend crashed'), 'error');
});

test('system log color keeps normal messages green and warnings distinct', () => {
  assert.equal(resolveSystemLogColor('INFO: backend ready'), '#55efc4');
  assert.equal(resolveSystemLogColor('WARNING: camera reconnect pending'), '#fdcb6e');
  assert.equal(resolveSystemLogColor('ERROR: backend crashed'), '#ff7675');
});

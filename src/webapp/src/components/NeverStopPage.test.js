import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('./NeverStopPage.jsx', import.meta.url), 'utf8');

test('Never Stop page isolates its legacy stylesheet in Shadow DOM', () => {
  assert.match(source, /style\.css\?inline/);
  assert.match(source, /attachShadow\(\{ mode: 'open' \}\)/);
  assert.match(source, /createPortal\(/);
  assert.match(source, /<style>\{neverStopStyles\}<\/style>/);
});

test('Never Stop page shows a local bridge error', () => {
  assert.match(source, /window\.vantagePlatform\?\.neverStop/);
  assert.match(source, /role="alert"/);
  assert.match(source, /<NeverStopApp isVisible=\{isVisible\}/);
});

test('Never Stop page forwards notification project choice to the retained view', () => {
  assert.match(source, /openRequest/);
  assert.match(source, /<NeverStopApp isVisible=\{isVisible\} openRequest=\{openRequest\}/);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const packageJson = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'));

test('package exposes frontend test and check scripts', () => {
  assert.ok(packageJson.scripts.test);
  assert.ok(packageJson.scripts.check);
  assert.match(packageJson.scripts.test, /node --test/);
  assert.match(packageJson.scripts.check, /npm run test/);
});

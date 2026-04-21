import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const viteConfigSource = readFileSync(new URL('./vite.config.js', import.meta.url), 'utf8');

test('vite config reads backend proxy target without process globals', () => {
  assert.ok(viteConfigSource.includes('loadEnv'));
  assert.equal(viteConfigSource.includes('process.env.VITE_BACKEND_PROXY_TARGET'), false);
});

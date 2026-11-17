import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('component monospace overrides retain the shared explicit Chinese fallback', () => {
  for (const file of ['Dashboard.jsx', 'Plots.jsx', 'SystemLogs.jsx']) {
    const source = readFileSync(new URL(`./${file}`, import.meta.url), 'utf8');
    const declarations = [...source.matchAll(/fontFamily:\s*'([^']+)'/g)];
    assert.ok(declarations.length, `${file} has a font override`);
    for (const [, value] of declarations) assert.equal(value, 'var(--font-mono)', file);
  }
  const project = readFileSync(new URL('./ProjectProgress.css', import.meta.url), 'utf8');
  assert.match(project, /\.commit-hash\s*\{[^}]*font-family:\s*var\(--font-mono\)/);
});

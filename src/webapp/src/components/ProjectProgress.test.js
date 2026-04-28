import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const projectProgressSource = readFileSync(new URL('./ProjectProgress.jsx', import.meta.url), 'utf8');

test('ProjectProgress keeps fetchProgress stable for the initial effect and retry button', () => {
  assert.match(projectProgressSource, /import React, \{ useState, useEffect, useCallback \} from 'react';/);
  assert.match(projectProgressSource, /const fetchProgress = useCallback\(async \(\) => \{/);
  assert.match(projectProgressSource, /\}, \[\]\);/);
  assert.match(projectProgressSource, /useEffect\(\(\) => \{\s*fetchProgress\(\);\s*\}, \[fetchProgress\]\);/s);
  assert.match(projectProgressSource, /setError\('project_progress\.error\.body'\);/);
  assert.match(projectProgressSource, /<p>\{t\(error\)\}<\/p>/);
  assert.equal(projectProgressSource.includes("setError(t('project_progress.error.body'))"), false);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const projectProgressSource = readFileSync(new URL('./ProjectProgress.jsx', import.meta.url), 'utf8');
const projectProgressCss = readFileSync(new URL('./ProjectProgress.css', import.meta.url), 'utf8');

test('ProjectProgress connects mount, focus, retry and unmount to the abortable refresher', () => {
  assert.match(projectProgressSource, /createProjectProgressRefresh/);
  assert.match(projectProgressSource, /focusTarget:\s*window/);
  assert.match(projectProgressSource, /signal\s*=>\s*fetchBackendJson\('\/api\/v1\/projects\/progress',\s*\{\s*retryPolicy:\s*'load',\s*signal\s*\}\)/);
  assert.match(projectProgressSource, /refreshRef\.current\?\.refresh\(\)/);
  assert.match(projectProgressSource, /refresh\.start\(\)/);
  assert.match(projectProgressSource, /refresh\.dispose\(\)/);
  assert.match(projectProgressSource, /onData:\s*\(result\)\s*=>\s*\{/);
  assert.match(projectProgressSource, /getProjectProgressViewState\(\{ data, loading, error \}\)/);
  assert.match(projectProgressSource, /viewState === 'content' && error/);
  assert.match(projectProgressSource, /role="alert"/);
  assert.match(projectProgressSource, /setError\('project_progress\.error\.body'\);/);
  assert.match(projectProgressSource, /<p>\{t\(error\)\}<\/p>/);
  assert.equal(projectProgressSource.includes("setError(t('project_progress.error.body'))"), false);
});

test('ProjectProgress refresh icon button is not clipped by global button padding', () => {
  assert.match(projectProgressCss, /\.refresh-btn\s*{[\s\S]*padding:\s*0;/);
  assert.match(projectProgressCss, /\.refresh-btn\s*{[\s\S]*line-height:\s*0;/);
  assert.match(projectProgressCss, /\.refresh-btn svg\s*{[\s\S]*display:\s*block;/);
});

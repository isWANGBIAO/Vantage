import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { prepareBuildVersion, syncReleaseMetadata } from './scripts/prepare-build-version.mjs';

const README = [
  '# Vantage',
  '',
  '```powershell',
  'git tag -a v1.2.3 -m "Vantage 1.2.3"',
  'git push origin v1.2.3',
  '```',
  '',
  'The tag must match the frontend package version, for example `v1.2.3` for package version `1.2.3`.',
  '',
].join('\n');

const RELEASE_YML = [
  'on:',
  '  workflow_dispatch:',
  '    inputs:',
  '      tag:',
  '        description: "Existing tag to release, for example v1.2.3"',
  '',
].join('\n');

function createRepo({ readme = README, release = RELEASE_YML } = {}) {
  const root = mkdtempSync(path.join(tmpdir(), 'vantage-version-'));
  const webappRoot = path.join(root, 'src', 'webapp');
  mkdirSync(path.join(root, '.github', 'workflows'), { recursive: true });
  mkdirSync(webappRoot, { recursive: true });
  writeFileSync(path.join(root, 'README.md'), readme, 'utf8');
  writeFileSync(path.join(root, '.github', 'workflows', 'release.yml'), release, 'utf8');
  writeFileSync(
    path.join(webappRoot, 'package.json'),
    `${JSON.stringify({ name: 'vantage', version: '1.2.3' }, null, 2)}\n`,
    'utf8',
  );
  writeFileSync(
    path.join(webappRoot, 'package-lock.json'),
    `${JSON.stringify({ name: 'vantage', version: '1.2.3', packages: { '': { version: '1.2.3' } } }, null, 2)}\n`,
    'utf8',
  );
  return { root, webappRoot };
}

function read(root, relative) {
  return readFileSync(path.join(root, relative), 'utf8');
}

test('a version bump keeps the release metadata in step', () => {
  const { root, webappRoot } = createRepo();
  try {
    const result = prepareBuildVersion({
      webappRoot,
      mode: 'bump',
      commit: 'abc1234',
      gitClean: false,
      now: new Date('2026-01-02T03:04:05Z'),
    });

    assert.equal(result.version, '1.2.4');
    assert.equal(result.bumped, true);
    assert.equal(result.metadata_synced.length, 2);

    const readme = read(root, 'README.md');
    assert.ok(readme.includes('git tag -a v1.2.4 -m "Vantage 1.2.4"'));
    assert.ok(readme.includes('git push origin v1.2.4'));
    assert.ok(readme.includes('for example `v1.2.4` for package version `1.2.4`'));
    assert.ok(!readme.includes('v1.2.3'));

    const release = read(root, '.github/workflows/release.yml');
    assert.ok(release.includes('for example v1.2.4'));
    assert.ok(!release.includes('v1.2.3'));

    const packageJson = JSON.parse(read(webappRoot, 'package.json'));
    const lockJson = JSON.parse(read(webappRoot, 'package-lock.json'));
    assert.equal(packageJson.version, '1.2.4');
    assert.equal(lockJson.version, '1.2.4');
    assert.equal(lockJson.packages[''].version, '1.2.4');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('metadata is left alone when the version does not bump', () => {
  const { root, webappRoot } = createRepo();
  try {
    const result = prepareBuildVersion({
      webappRoot,
      mode: 'sync',
      commit: 'abc1234',
      gitClean: true,
    });

    assert.equal(result.bumped, false);
    assert.deepEqual(result.metadata_synced, []);
    assert.equal(read(root, 'README.md'), README);
    assert.equal(read(root, '.github/workflows/release.yml'), RELEASE_YML);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('an unexpected metadata layout is reported instead of silently skipped', () => {
  const { root, webappRoot } = createRepo({ readme: '# Vantage\n\nno release instructions here\n' });
  const warnings = [];
  try {
    const synced = syncReleaseMetadata({
      webappRoot,
      version: '1.2.4',
      previousVersion: '1.2.3',
      warn: (message) => warnings.push(message),
    });

    assert.equal(synced.length, 1);
    assert.equal(read(root, 'README.md'), '# Vantage\n\nno release instructions here\n');
    assert.equal(warnings.length, 3);
    assert.ok(warnings.every((message) => message.includes('not updated')));
    // The workflow file is independent, so it is still updated.
    assert.ok(read(root, '.github/workflows/release.yml').includes('for example v1.2.4'));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('a missing metadata file is reported and does not abort the build version', () => {
  const { root, webappRoot } = createRepo();
  const warnings = [];
  try {
    rmSync(path.join(root, '.github', 'workflows', 'release.yml'));
    const result = prepareBuildVersion({
      webappRoot,
      mode: 'bump',
      commit: 'abc1234',
      gitClean: false,
      warn: (message) => warnings.push(message),
    });

    assert.equal(result.version, '1.2.4');
    assert.equal(result.metadata_synced.length, 1);
    assert.ok(warnings.some((message) => message.includes('not found')));
    assert.ok(read(root, 'README.md').includes('v1.2.4'));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

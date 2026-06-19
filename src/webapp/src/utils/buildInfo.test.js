import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { resolveAppBuildInfo } = require('./buildInfo.cjs');

test('resolveAppBuildInfo refreshes stale source metadata from git in development mode', () => {
  const result = resolveAppBuildInfo({
    staticBuildInfo: {
      version: '1.0.58',
      build_date: '2026-06-16T04:14:44.200Z',
      build_commit: 'old1234+dirty',
    },
    appMode: 'development',
    isPackaged: false,
    readGitCommit: () => 'new5678',
    readGitClean: () => true,
    now: () => '2026-06-19T02:00:00.000Z',
  });

  assert.deepEqual(result, {
    version: '1.0.58',
    build_date: '2026-06-19T02:00:00.000Z',
    build_commit: 'new5678',
  });
});

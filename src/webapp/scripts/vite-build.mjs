import { spawnSync } from 'node:child_process';
import { existsSync, realpathSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import buildCache from '../src/utils/frontendBuildCache.cjs';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const webappRoot = realpathSync(path.resolve(scriptDir, '..'));
const viteCli = path.join(
  webappRoot,
  'node_modules',
  'vite',
  'bin',
  'vite.js',
);

if (!existsSync(viteCli)) {
  throw new Error(`Vite executable not found: ${viteCli}`);
}

const inputs = buildCache.inputFingerprint(webappRoot);
rmSync(path.join(webappRoot, 'dist', buildCache.STATE_NAME), { force: true });
const result = spawnSync(process.execPath, [viteCli, 'build', webappRoot], {
  cwd: webappRoot,
  stdio: 'inherit',
});

if (result.error) {
  throw result.error;
}

if (result.status === 0) {
  buildCache.recordBuild(webappRoot, inputs);
}
process.exit(result.status ?? 1);

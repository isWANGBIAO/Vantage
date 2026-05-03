import { spawnSync } from 'node:child_process';
import { existsSync, realpathSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

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

const result = spawnSync(process.execPath, [viteCli, 'build', webappRoot], {
  cwd: webappRoot,
  stdio: 'inherit',
});

if (result.error) {
  throw result.error;
}

process.exit(result.status ?? 1);

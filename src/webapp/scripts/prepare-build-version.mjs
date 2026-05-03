import { execSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const defaultWebappRoot = path.resolve(scriptDir, '..');

function readJson(filePath) {
  return JSON.parse(readFileSync(filePath, 'utf8').replace(/^\uFEFF/, ''));
}

function writeJson(filePath, payload) {
  writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
}

export function bumpPatchVersion(version) {
  const parts = String(version || '0.0.0').split('.').map((part) => Number.parseInt(part, 10));
  const [major = 0, minor = 0, patch = 0] = parts.map((part) => (Number.isFinite(part) ? part : 0));
  return `${major}.${minor}.${patch + 1}`;
}

function resolveGitCommit(webappRoot) {
  try {
    return execSync('git rev-parse --short HEAD', {
      cwd: path.resolve(webappRoot, '..', '..'),
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
  } catch {
    return null;
  }
}

export function prepareBuildVersion({
  webappRoot = defaultWebappRoot,
  now = new Date(),
  commit = resolveGitCommit(webappRoot),
} = {}) {
  const packagePath = path.join(webappRoot, 'package.json');
  const lockPath = path.join(webappRoot, 'package-lock.json');
  const buildInfoPath = path.join(webappRoot, 'build-info.json');
  const packageJson = readJson(packagePath);
  const nextVersion = bumpPatchVersion(packageJson.version);
  packageJson.version = nextVersion;
  writeJson(packagePath, packageJson);

  if (existsSync(lockPath)) {
    const lockJson = readJson(lockPath);
    lockJson.version = nextVersion;
    if (lockJson.packages?.['']) {
      lockJson.packages[''].version = nextVersion;
    }
    writeJson(lockPath, lockJson);
  }

  const buildInfo = {
    version: nextVersion,
    build_date: now.toISOString(),
    build_commit: commit || null,
  };
  writeJson(buildInfoPath, buildInfo);

  return buildInfo;
}

function resolveCliWebappRoot(argv) {
  const rootFlagIndex = argv.indexOf('--webapp-root');
  if (rootFlagIndex >= 0 && argv[rootFlagIndex + 1]) {
    return path.resolve(argv[rootFlagIndex + 1]);
  }
  return defaultWebappRoot;
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : '';
const modulePath = fileURLToPath(import.meta.url);
if (invokedPath && path.basename(invokedPath) === path.basename(modulePath)) {
  const result = prepareBuildVersion({ webappRoot: resolveCliWebappRoot(process.argv.slice(2)) });
  console.log(`Prepared Vantage build ${result.version} (${result.build_date}, ${result.build_commit || 'no git commit'})`);
}

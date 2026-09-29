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

// The release metadata carries the version in prose, and nothing else keeps it
// in step with package.json. A dirty tree bumps the patch version on every
// RUN.bat build, so these files would drift on each build without this sync.
// Each replacement is anchored on its full previous line, so a file that does
// not carry the expected line is reported instead of edited blindly.
export function syncReleaseMetadata({ webappRoot, version, previousVersion, warn = console.warn }) {
  const root = path.resolve(webappRoot, '..', '..');
  const targets = [
    {
      file: path.join(root, 'README.md'),
      replacements: [
        [
          `git tag -a v${previousVersion} -m "Vantage ${previousVersion}"`,
          `git tag -a v${version} -m "Vantage ${version}"`,
        ],
        [`git push origin v${previousVersion}`, `git push origin v${version}`],
        [
          `for example \`v${previousVersion}\` for package version \`${previousVersion}\``,
          `for example \`v${version}\` for package version \`${version}\``,
        ],
      ],
    },
    {
      file: path.join(root, '.github', 'workflows', 'release.yml'),
      replacements: [[`for example v${previousVersion}`, `for example v${version}`]],
    },
  ];

  const synced = [];
  for (const target of targets) {
    if (!existsSync(target.file)) {
      warn(`Release metadata not found, skipped: ${target.file}`);
      continue;
    }
    const original = readFileSync(target.file, 'utf8');
    let updated = original;
    for (const [from, to] of target.replacements) {
      if (!updated.includes(from)) {
        warn(`Release metadata is out of date and was not updated: ${from}`);
        continue;
      }
      updated = updated.split(from).join(to);
    }
    if (updated !== original) {
      writeFileSync(target.file, updated, 'utf8');
      synced.push(target.file);
    }
  }
  return synced;
}

function resolveGitCleanState(webappRoot) {
  try {
    const output = execSync('git status --porcelain --untracked-files=no', {
      cwd: path.resolve(webappRoot, '..', '..'),
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    });
    return output.trim().length === 0;
  } catch {
    return false;
  }
}

function formatBuildCommit(commit, gitClean) {
  if (!commit) {
    return null;
  }
  return gitClean ? commit : `${commit}+dirty`;
}

export function prepareBuildVersion({
  webappRoot = defaultWebappRoot,
  now = new Date(),
  commit = resolveGitCommit(webappRoot),
  mode = 'bump',
  gitClean = resolveGitCleanState(webappRoot),
  syncMetadata = true,
  warn = console.warn,
} = {}) {
  const packagePath = path.join(webappRoot, 'package.json');
  const lockPath = path.join(webappRoot, 'package-lock.json');
  const buildInfoPath = path.join(webappRoot, 'build-info.json');
  const packageJson = readJson(packagePath);

  const normalizedMode = String(mode || 'bump').toLowerCase();
  const existingBuildInfo = existsSync(buildInfoPath) ? readJson(buildInfoPath) : null;
  const alreadyPreparedForCommit = existingBuildInfo?.version === packageJson.version
    && String(existingBuildInfo?.build_commit || '').replace(/\+dirty$/, '') === commit;
  const shouldBump = normalizedMode === 'auto'
    ? !gitClean && !alreadyPreparedForCommit
    : normalizedMode !== 'sync';
  const buildCommit = formatBuildCommit(commit, gitClean);

  if (!shouldBump) {
    const buildInfo = {
      version: packageJson.version,
      build_date: existingBuildInfo?.build_commit === buildCommit
        && existingBuildInfo?.version === packageJson.version
        && existingBuildInfo?.build_date
        ? existingBuildInfo.build_date
        : now.toISOString(),
      build_commit: buildCommit,
    };
    if (
      existingBuildInfo?.version !== buildInfo.version
      || existingBuildInfo?.build_date !== buildInfo.build_date
      || existingBuildInfo?.build_commit !== buildInfo.build_commit
    ) {
      writeJson(buildInfoPath, buildInfo);
    }
    return {
      version: buildInfo.version,
      build_date: buildInfo.build_date,
      build_commit: buildInfo.build_commit,
      bumped: false,
      metadata_synced: [],
    };
  }

  const previousVersion = packageJson.version;
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

  const metadataSynced = syncMetadata
    ? syncReleaseMetadata({
      webappRoot,
      version: nextVersion,
      previousVersion,
      warn,
    })
    : [];

  const buildInfo = {
    version: nextVersion,
    build_date: now.toISOString(),
    build_commit: buildCommit,
    bumped: true,
  };
  writeJson(buildInfoPath, {
    version: buildInfo.version,
    build_date: buildInfo.build_date,
    build_commit: buildInfo.build_commit,
  });

  return { ...buildInfo, metadata_synced: metadataSynced };
}

function resolveCliWebappRoot(argv) {
  const rootFlagIndex = argv.indexOf('--webapp-root');
  if (rootFlagIndex >= 0 && argv[rootFlagIndex + 1]) {
    return path.resolve(argv[rootFlagIndex + 1]);
  }
  return defaultWebappRoot;
}

function resolveCliMode(argv) {
  const modeFlagIndex = argv.indexOf('--mode');
  if (modeFlagIndex >= 0 && argv[modeFlagIndex + 1]) {
    return argv[modeFlagIndex + 1];
  }
  return 'bump';
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : '';
const modulePath = fileURLToPath(import.meta.url);
if (invokedPath && path.basename(invokedPath) === path.basename(modulePath)) {
  const cliArgs = process.argv.slice(2);
  const result = prepareBuildVersion({
    webappRoot: resolveCliWebappRoot(cliArgs),
    mode: resolveCliMode(cliArgs),
    syncMetadata: !cliArgs.includes('--no-sync-metadata'),
  });
  const syncedCount = result.metadata_synced?.length ?? 0;
  if (result.bumped) {
    console.log(`Prepared Vantage build ${result.version} (${result.build_date}, ${result.build_commit || 'no git commit'})`);
    if (syncedCount > 0) {
      console.log(`Synced release metadata to ${result.version} in ${syncedCount} file(s)`);
    }
  } else {
    console.log(`Build version unchanged at ${result.version}`);
  }
}

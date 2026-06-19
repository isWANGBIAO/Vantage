const { execFileSync } = require('node:child_process');

function normalizeOptionalString(value) {
  if (typeof value !== 'string') {
    return null;
  }
  const normalized = value.trim();
  return normalized || null;
}

function readGitCommit(projectRoot) {
  if (!projectRoot) {
    return null;
  }
  try {
    return execFileSync('git', ['rev-parse', '--short', 'HEAD'], {
      cwd: projectRoot,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
  } catch {
    return null;
  }
}

function readGitClean(projectRoot) {
  if (!projectRoot) {
    return false;
  }
  try {
    const output = execFileSync('git', ['status', '--porcelain', '--untracked-files=no'], {
      cwd: projectRoot,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    });
    return output.trim().length === 0;
  } catch {
    return false;
  }
}

function formatGitCommit(commit, gitClean) {
  const normalizedCommit = normalizeOptionalString(commit);
  if (!normalizedCommit) {
    return null;
  }
  return gitClean ? normalizedCommit : `${normalizedCommit}+dirty`;
}

function sanitizeBuildInfo(buildInfo) {
  const safeBuildInfo = buildInfo && typeof buildInfo === 'object' ? buildInfo : {};
  return {
    version: normalizeOptionalString(safeBuildInfo.version),
    build_date: normalizeOptionalString(safeBuildInfo.build_date),
    build_commit: normalizeOptionalString(safeBuildInfo.build_commit),
  };
}

function shouldUseStaticBuildInfo({ appMode, isPackaged }) {
  return Boolean(isPackaged || appMode === 'packaged');
}

function resolveAppBuildInfo({
  staticBuildInfo = {},
  projectRoot = null,
  appMode = 'development',
  isPackaged = false,
  readGitCommit: readGitCommitFn = readGitCommit,
  readGitClean: readGitCleanFn = readGitClean,
  now = () => new Date().toISOString(),
} = {}) {
  const normalizedStaticBuildInfo = sanitizeBuildInfo(staticBuildInfo);
  if (shouldUseStaticBuildInfo({ appMode, isPackaged })) {
    return normalizedStaticBuildInfo;
  }

  const commit = readGitCommitFn(projectRoot);
  const buildCommit = formatGitCommit(commit, readGitCleanFn(projectRoot));
  if (!buildCommit) {
    return normalizedStaticBuildInfo;
  }

  return {
    ...normalizedStaticBuildInfo,
    build_date:
      normalizedStaticBuildInfo.build_commit === buildCommit
        ? normalizedStaticBuildInfo.build_date
        : now(),
    build_commit: buildCommit,
  };
}

module.exports = {
  formatGitCommit,
  readGitClean,
  readGitCommit,
  resolveAppBuildInfo,
};

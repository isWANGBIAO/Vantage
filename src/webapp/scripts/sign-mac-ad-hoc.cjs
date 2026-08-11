const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const { walkAsync } = require('@electron/osx-sign');
const { redactSensitiveText } = require('../src/utils/boundedLogger.cjs');

const PROJECT_ROOT = path.resolve(__dirname, '..', '..', '..');
const BOUNDED_COMMAND_RUNNER = path.join(
  PROJECT_ROOT,
  'src',
  'scripts',
  'run_bounded_command.py',
);
const BOOTSTRAP_PYTHON = process.env.VANTAGE_BOOTSTRAP_PYTHON || 'python3';
const COMMAND_TIMEOUT_SECONDS = 300;
const COMMAND_BRIDGE_TIMEOUT_MS = 310 * 1000;
const COMMAND_OUTPUT_LIMIT_BYTES = 16 * 1024;
const COMMAND_BRIDGE_MAX_BUFFER_BYTES = 64 * 1024;
const REDACTION_PATH_PREFIXES = [
  { label: '<PROJECT_ROOT>', prefix: PROJECT_ROOT },
  { label: '<HOME>', prefix: os.homedir() },
  { label: '<TEMP>', prefix: os.tmpdir() },
];

const SIGNING_IDENTITY = process.env.VANTAGE_MAC_CODESIGN_IDENTITY || '-';
const USE_STABLE_DESIGNATED_REQUIREMENT = process.env.VANTAGE_MAC_CODESIGN_STABLE_REQUIREMENT !== '0';
const XATTR_BATCH_SIZE = 128;
const XATTR_BATCH_PATH_BYTES = 24 * 1024;

const AD_HOC_MAIN_ENTITLEMENTS = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>com.apple.security.cs.allow-jit</key>
    <true/>
    <key>com.apple.security.cs.disable-library-validation</key>
    <true/>
    <key>com.apple.security.device.audio-input</key>
    <true/>
    <key>com.apple.security.device.bluetooth</key>
    <true/>
    <key>com.apple.security.device.camera</key>
    <true/>
    <key>com.apple.security.device.print</key>
    <true/>
    <key>com.apple.security.device.usb</key>
    <true/>
    <key>com.apple.security.personal-information.location</key>
    <true/>
  </dict>
</plist>
`;

function boundedErrorDetail(error) {
  const rawDetail = error?.stderr?.toString()
    || error?.stdout?.toString()
    || '';
  const redacted = redactSensitiveText(rawDetail, REDACTION_PATH_PREFIXES);
  return Buffer.from(redacted, 'utf8')
    .subarray(0, COMMAND_OUTPUT_LIMIT_BYTES)
    .toString('utf8')
    .trim();
}

function executeBoundedCommand(command, args) {
  const bridgeArgs = [
    BOUNDED_COMMAND_RUNNER,
    '--timeout-seconds',
    String(COMMAND_TIMEOUT_SECONDS),
    '--output-limit-bytes',
    String(COMMAND_OUTPUT_LIMIT_BYTES),
  ];
  for (const mapping of REDACTION_PATH_PREFIXES) {
    bridgeArgs.push('--redact-path', mapping.label, mapping.prefix);
  }
  bridgeArgs.push('--', command, ...args);

  return execFileSync(BOOTSTRAP_PYTHON, bridgeArgs, {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: COMMAND_BRIDGE_TIMEOUT_MS,
    maxBuffer: COMMAND_BRIDGE_MAX_BUFFER_BYTES,
  });
}

function run(command, args, { ignoreFailure = false } = {}) {
  try {
    executeBoundedCommand(command, args);
  } catch (error) {
    if (ignoreFailure) {
      return false;
    }
    const detail = boundedErrorDetail(error);
    const suffix = detail ? `\n${detail}` : '';
    throw new Error(`macOS signing command failed${suffix}`);
  }
  return true;
}

function capture(command, args) {
  try {
    return executeBoundedCommand(command, args).trim();
  } catch (error) {
    const detail = boundedErrorDetail(error);
    const suffix = detail ? `\n${detail}` : '';
    throw new Error(`macOS signing command failed${suffix}`);
  }
}

function collectSignBlockingAttributeTargets(targetPath, targets = []) {
  const stat = fs.lstatSync(targetPath);
  if (stat.isSymbolicLink()) {
    return targets;
  }
  if (stat.isFile() && stat.nlink !== 1) {
    throw new Error('The macOS app bundle contains a hard-linked file');
  }

  targets.push(targetPath);
  if (stat.isDirectory()) {
    for (const entryName of fs.readdirSync(targetPath)) {
      collectSignBlockingAttributeTargets(path.join(targetPath, entryName), targets);
    }
  }
  return targets;
}

function clearBundleSignBlockingAttributes(bundlePath) {
  const targets = collectSignBlockingAttributeTargets(bundlePath);
  let batch = [];
  let batchPathBytes = 0;
  for (const targetPath of targets) {
    const targetPathBytes = Buffer.byteLength(targetPath, 'utf8') + 1;
    if (targetPathBytes > XATTR_BATCH_PATH_BYTES) {
      throw new Error('A macOS app bundle path exceeds the xattr command limit');
    }
    if (
      batch.length > 0
      && (batch.length >= XATTR_BATCH_SIZE
        || batchPathBytes + targetPathBytes > XATTR_BATCH_PATH_BYTES)
    ) {
      run('xattr', ['-c', ...batch]);
      batch = [];
      batchPathBytes = 0;
    }
    batch.push(targetPath);
    batchPathBytes += targetPathBytes;
  }
  if (batch.length > 0) {
    run('xattr', ['-c', ...batch]);
  }
}

function depth(filePath) {
  return filePath.split(path.sep).length;
}

function isBundlePath(filePath) {
  const stat = fs.lstatSync(filePath);
  return stat.isDirectory() && /\.(app|framework|xpc|appex|plugin|bundle)$/i.test(filePath);
}

function isMachOFile(filePath) {
  const stat = fs.lstatSync(filePath);
  if (!stat.isFile()) {
    return false;
  }

  const buffer = Buffer.alloc(4);
  let fd = null;
  try {
    fd = fs.openSync(filePath, 'r');
    if (fs.readSync(fd, buffer, 0, 4, 0) !== 4) {
      return false;
    }
  } catch {
    return false;
  } finally {
    if (fd !== null) {
      fs.closeSync(fd);
    }
  }

  const magic = buffer.toString('hex');
  return [
    'feedface',
    'cefaedfe',
    'feedfacf',
    'cffaedfe',
    'cafebabe',
    'bebafeca',
    'cafebabf',
    'bfbafeca',
  ].includes(magic);
}

function findPackageRoot(packageName) {
  let currentPath = path.dirname(require.resolve(packageName));
  while (currentPath !== path.dirname(currentPath)) {
    if (fs.existsSync(path.join(currentPath, 'package.json'))) {
      return currentPath;
    }
    currentPath = path.dirname(currentPath);
  }
  return null;
}

function resolveOsxSignEntitlement(fileName) {
  const packageRoot = findPackageRoot('@electron/osx-sign');
  if (!packageRoot) {
    return null;
  }

  const entitlementPath = path.join(packageRoot, 'entitlements', fileName);
  return fs.existsSync(entitlementPath) ? entitlementPath : null;
}

function readBundleIdentifier(appPath) {
  const infoPlistPath = path.join(appPath, 'Contents', 'Info.plist');
  const bundleIdentifier = capture('plutil', [
    '-extract',
    'CFBundleIdentifier',
    'raw',
    '-o',
    '-',
    infoPlistPath,
  ]);
  if (!/^[A-Za-z0-9][A-Za-z0-9.-]+$/.test(bundleIdentifier)) {
    throw new Error(`Unsafe macOS bundle identifier for signing requirement: ${bundleIdentifier}`);
  }
  return bundleIdentifier;
}

function readCachedBundleIdentifier(bundlePath, signingOptions = {}) {
  if (!signingOptions.bundleIdentifierCache) {
    signingOptions.bundleIdentifierCache = new Map();
  }
  if (!signingOptions.bundleIdentifierCache.has(bundlePath)) {
    signingOptions.bundleIdentifierCache.set(bundlePath, readBundleIdentifier(bundlePath));
  }
  return signingOptions.bundleIdentifierCache.get(bundlePath);
}

function createAdHocMainEntitlements(tempRoot) {
  const entitlementsPath = path.join(tempRoot, 'vantage-ad-hoc-main.entitlements.plist');
  fs.writeFileSync(entitlementsPath, AD_HOC_MAIN_ENTITLEMENTS, 'utf8');
  return entitlementsPath;
}

function shouldUseAdHocMainEntitlements(filePath, signingOptions = {}) {
  const baseName = path.basename(filePath);
  return filePath === signingOptions.topLevelAppPath
    || filePath === signingOptions.mainExecutablePath
    || baseName.startsWith(`${signingOptions.productName || 'Vantage'} Helper`)
    || baseName === 'VantageBackend';
}

function entitlementsForPath(filePath, signingOptions = {}) {
  if (
    signingOptions.mainEntitlementsPath
    && shouldUseAdHocMainEntitlements(filePath, signingOptions)
  ) {
    return signingOptions.mainEntitlementsPath;
  }

  const baseName = path.basename(filePath);
  if (baseName.includes('Electron Helper (Renderer)')) {
    return resolveOsxSignEntitlement('default.darwin.renderer.plist');
  }
  if (baseName.includes('Electron Helper (GPU)')) {
    return resolveOsxSignEntitlement('default.darwin.gpu.plist');
  }
  if (baseName.includes('Electron Helper (Plugin)')) {
    return resolveOsxSignEntitlement('default.darwin.plugin.plist');
  }
  return resolveOsxSignEntitlement('default.darwin.plist');
}

function nearestAppBundlePath(filePath, stopPath) {
  const resolvedStopPath = path.resolve(stopPath);
  let currentPath = filePath;

  try {
    if (!fs.lstatSync(currentPath).isDirectory()) {
      currentPath = path.dirname(currentPath);
    }
  } catch {
    return null;
  }

  while (path.resolve(currentPath).startsWith(resolvedStopPath)) {
    if (
      /\.app$/i.test(path.basename(currentPath))
      && fs.existsSync(path.join(currentPath, 'Contents', 'Info.plist'))
    ) {
      return currentPath;
    }

    const parentPath = path.dirname(currentPath);
    if (parentPath === currentPath) {
      break;
    }
    currentPath = parentPath;
  }
  return null;
}

function isProductHelperAppPath(appPath, signingOptions = {}) {
  const productName = signingOptions.productName || 'Vantage';
  return path.basename(appPath).startsWith(`${productName} Helper`);
}

function stableCodeIdentifierForPath(filePath, signingOptions = {}) {
  if (
    !USE_STABLE_DESIGNATED_REQUIREMENT
    || !signingOptions.stableDesignatedRequirement
  ) {
    return null;
  }

  if (
    filePath === signingOptions.topLevelAppPath
    || filePath === signingOptions.mainExecutablePath
  ) {
    return signingOptions.bundleIdentifier;
  }
  if (path.basename(filePath) === 'VantageBackend') {
    return `${signingOptions.bundleIdentifier}.VantageBackend`;
  }

  const appBundlePath = nearestAppBundlePath(
    filePath,
    signingOptions.topLevelAppPath || path.parse(filePath).root,
  );
  if (appBundlePath && isProductHelperAppPath(appBundlePath, signingOptions)) {
    return readCachedBundleIdentifier(appBundlePath, signingOptions);
  }

  return null;
}

function stableDesignatedRequirementForIdentifier(codeIdentifier) {
  return `=designated => identifier "${codeIdentifier}"`;
}

function stableDesignatedRequirementForPath(filePath, signingOptions = {}) {
  const codeIdentifier = stableCodeIdentifierForPath(filePath, signingOptions);
  return codeIdentifier ? stableDesignatedRequirementForIdentifier(codeIdentifier) : null;
}

function codesignPath(filePath, signingOptions = {}) {
  const args = [
    '--force',
    '--sign',
    SIGNING_IDENTITY,
    '--timestamp=none',
    '--options',
    'runtime',
  ];
  const entitlementsPath = entitlementsForPath(filePath, signingOptions);
  if (entitlementsPath) {
    args.push('--entitlements', entitlementsPath);
  }
  const stableCodeIdentifier = stableCodeIdentifierForPath(filePath, signingOptions);
  if (stableCodeIdentifier && !isBundlePath(filePath)) {
    args.push('--identifier', stableCodeIdentifier);
  }
  const stableDesignatedRequirement = stableDesignatedRequirementForPath(filePath, signingOptions);
  if (stableDesignatedRequirement) {
    args.push('--requirements', stableDesignatedRequirement);
  }
  args.push(filePath);
  run('codesign', args);
}

function codesignPathWithShell(filePath, signingOptions = {}) {
  codesignPath(filePath, signingOptions);
}

function codesignTopLevelApp(appPath, signingOptions = {}) {
  clearBundleSignBlockingAttributes(appPath);
  const args = [
    '--force',
    '--sign',
    SIGNING_IDENTITY,
    '--timestamp=none',
    '--options',
    'runtime',
  ];
  const entitlementsPath = entitlementsForPath(appPath, signingOptions);
  if (entitlementsPath) {
    args.push('--entitlements', entitlementsPath);
  }
  const stableDesignatedRequirement = stableDesignatedRequirementForPath(appPath, signingOptions);
  if (stableDesignatedRequirement) {
    args.push('--requirements', stableDesignatedRequirement);
  }
  args.push(appPath);
  run('codesign', args);
  run('codesign', ['--verify', '--deep', '--strict', '--verbose=2', appPath]);
}

function findAppBundle(context) {
  const appOutDir = context?.appOutDir;
  if (!appOutDir || !fs.existsSync(appOutDir)) {
    return null;
  }

  const productFilename = context?.packager?.appInfo?.productFilename;
  if (productFilename) {
    const candidatePath = path.join(appOutDir, `${productFilename}.app`);
    if (fs.existsSync(candidatePath)) {
      return candidatePath;
    }
  }

  const appName = fs.readdirSync(appOutDir).find((entry) => entry.endsWith('.app'));
  return appName ? path.join(appOutDir, appName) : null;
}

async function signAppBundle(appPath) {
  clearBundleSignBlockingAttributes(appPath);

  const bundleIdentifier = readBundleIdentifier(appPath);
  const mainExecutablePath = path.join(
    appPath,
    'Contents',
    'MacOS',
    path.basename(appPath, '.app'),
  );
  const signingOptions = {
    bundleIdentifier,
    bundleIdentifierCache: new Map([[appPath, bundleIdentifier]]),
    mainEntitlementsPath: createAdHocMainEntitlements(path.dirname(appPath)),
    mainExecutablePath,
    productName: path.basename(appPath, '.app'),
    stableDesignatedRequirement: `=designated => identifier "${bundleIdentifier}"`,
    topLevelAppPath: appPath,
  };
  const contentsPath = path.join(appPath, 'Contents');
  const walkedPaths = (await walkAsync(contentsPath))
    .map((entry) => (typeof entry === 'string' ? entry : entry.path))
    .filter(Boolean);

  const signablePaths = walkedPaths
    .filter((targetPath) => {
      if (targetPath === mainExecutablePath) {
        return false;
      }
      return isBundlePath(targetPath) || isMachOFile(targetPath);
    })
    .sort((leftPath, rightPath) => depth(rightPath) - depth(leftPath));

  for (const targetPath of signablePaths) {
    codesignPath(targetPath, signingOptions);
  }

  if (fs.existsSync(mainExecutablePath)) {
    const mainExecutableStat = fs.lstatSync(mainExecutablePath);
    if (!mainExecutableStat.isFile() || mainExecutableStat.isSymbolicLink()) {
      throw new Error('The main macOS executable must be a regular file');
    }
    codesignPathWithShell(mainExecutablePath, signingOptions);
  }

  codesignTopLevelApp(appPath, signingOptions);
}

async function signMacAdHoc(context) {
  if (context?.electronPlatformName !== 'darwin') {
    return;
  }

  const outputAppPath = findAppBundle(context);
  if (!outputAppPath) {
    throw new Error('Could not find macOS app bundle to sign');
  }

  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-mac-sign-'));
  const appPath = path.join(tempRoot, path.basename(outputAppPath));

  try {
    run('ditto', [outputAppPath, appPath]);
    await signAppBundle(appPath);
    fs.rmSync(outputAppPath, { recursive: true, force: true });
    run('ditto', [appPath, outputAppPath]);
    clearBundleSignBlockingAttributes(outputAppPath);
    run('codesign', ['--verify', '--deep', '--strict', '--verbose=2', outputAppPath]);
  } catch (error) {
    fs.rmSync(outputAppPath, { recursive: true, force: true });
    throw error;
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
}

module.exports = signMacAdHoc;
module.exports._testing = {
  collectSignBlockingAttributeTargets,
};

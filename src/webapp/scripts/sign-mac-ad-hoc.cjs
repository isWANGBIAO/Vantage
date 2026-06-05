const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const { walkAsync } = require('@electron/osx-sign');

const SIGNING_IDENTITY = process.env.VANTAGE_MAC_CODESIGN_IDENTITY || '-';
const USE_STABLE_DESIGNATED_REQUIREMENT = process.env.VANTAGE_MAC_CODESIGN_STABLE_REQUIREMENT !== '0';
const SIGN_BLOCKING_XATTRS = [
  'com.apple.FinderInfo',
  'com.apple.ResourceFork',
  'com.apple.fileprovider.fpfs#P',
  'com.apple.macl',
  'com.apple.quarantine',
];

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

function commandPath(filePath) {
  return path.relative(process.cwd(), filePath) || filePath;
}

function formatCommandArg(arg) {
  return path.isAbsolute(arg) ? commandPath(arg) : arg;
}

function run(command, args, { ignoreFailure = false } = {}) {
  try {
    execFileSync(command, args, { stdio: 'pipe' });
  } catch (error) {
    if (ignoreFailure) {
      return false;
    }
    const stderr = error.stderr?.toString().trim();
    const suffix = stderr ? `\n${stderr}` : '';
    throw new Error(`${command} ${args.map(formatCommandArg).join(' ')} failed${suffix}`);
  }
  return true;
}

function capture(command, args) {
  return execFileSync(command, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}

function clearSignBlockingAttributes(targetPath) {
  for (const attribute of SIGN_BLOCKING_XATTRS) {
    run('xattr', ['-d', attribute, targetPath], { ignoreFailure: true });
  }
}

function clearSignBlockingAttributesRecursive(targetPath) {
  clearSignBlockingAttributes(targetPath);

  let stat = null;
  try {
    stat = fs.lstatSync(targetPath);
  } catch {
    return;
  }

  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    return;
  }

  for (const entryName of fs.readdirSync(targetPath)) {
    clearSignBlockingAttributesRecursive(path.join(targetPath, entryName));
  }
}

function clearPathAndAncestors(targetPath, stopPath) {
  let currentPath = targetPath;
  const resolvedStopPath = path.resolve(stopPath);

  while (path.resolve(currentPath).startsWith(resolvedStopPath)) {
    clearSignBlockingAttributes(currentPath);
    const parentPath = path.dirname(currentPath);
    if (parentPath === currentPath) {
      break;
    }
    currentPath = parentPath;
  }
}

function clearBundleSignBlockingAttributes(bundlePath) {
  run('xattr', ['-cr', bundlePath], { ignoreFailure: true });
  clearSignBlockingAttributesRecursive(bundlePath);
  clearPathAndAncestors(bundlePath, bundlePath);
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

function createAdHocMainEntitlements(tempRoot) {
  const entitlementsPath = path.join(tempRoot, 'vantage-ad-hoc-main.entitlements.plist');
  fs.writeFileSync(entitlementsPath, AD_HOC_MAIN_ENTITLEMENTS, 'utf8');
  return entitlementsPath;
}

function shouldUseAdHocMainEntitlements(filePath, signingOptions = {}) {
  return filePath === signingOptions.topLevelAppPath
    || filePath === signingOptions.mainExecutablePath
    || path.basename(filePath) === 'VantageBackend';
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

function stableDesignatedRequirementForPath(filePath, signingOptions = {}) {
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
    return signingOptions.stableDesignatedRequirement;
  }
  return null;
}

function codesignPath(filePath, signingOptions = {}) {
  clearPathAndAncestors(filePath, path.dirname(filePath));

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
    mainEntitlementsPath: createAdHocMainEntitlements(path.dirname(appPath)),
    mainExecutablePath,
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
    codesignPathWithShell(mainExecutablePath, signingOptions);
  }

  codesignTopLevelApp(appPath, signingOptions);
}

module.exports = async function signMacAdHoc(context) {
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
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
};

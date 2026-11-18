const { execFileSync } = require('node:child_process');
const path = require('node:path');
const { Arch } = require('electron-builder');

const BACKEND_BINARY = path.resolve(
  __dirname, '../../..', 'build/backend-runtime/stage/VantageBackend/VantageBackend',
);

function readMachOArchitectures(binary) {
  return execFileSync('/usr/bin/lipo', ['-archs', binary], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: 5000,
    maxBuffer: 4096,
  });
}

function requireMacosArm64(context, {
  hostPlatform = process.platform,
  hostArch = process.arch,
  inspectArchitectures = readMachOArchitectures,
} = {}) {
  if (!['darwin', 'mas', 'mas-dev'].includes(context.electronPlatformName)) return;
  if (hostPlatform !== 'darwin' || hostArch !== 'arm64' || context.arch !== Arch.arm64) {
    throw new Error('Vantage macOS packaging requires native Apple Silicon Node.js and an arm64 target.');
  }

  // Direct electron-builder calls can bypass RUN.sh or reuse an old staged backend.
  let architectures;
  try {
    architectures = inspectArchitectures(BACKEND_BINARY).trim();
  } catch {
    throw new Error('Cannot verify the staged macOS VantageBackend architecture. Build it with RUN.sh.');
  }
  if (architectures !== 'arm64') {
    throw new Error('The staged macOS VantageBackend must be arm64-only. Rebuild it with RUN.sh.');
  }
}

module.exports = requireMacosArm64;

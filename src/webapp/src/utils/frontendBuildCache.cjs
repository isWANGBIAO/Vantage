const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const STATE_NAME = '.vantage-build-state.json';
const INPUTS = [
  'src', 'public', 'never-stop/ui', 'index.html', 'package.json',
  'package-lock.json', 'vite.config.js', 'scripts/vite-build.mjs',
  '.env', '.env.local', '.env.production', '.env.production.local',
];

function fingerprintFiles(root, entries, excluded = new Set()) {
  const files = {};
  function visit(relative) {
    if (excluded.has(relative)) return;
    const absolute = path.join(root, relative);
    if (!fs.existsSync(absolute)) return;
    if (fs.statSync(absolute).isDirectory()) {
      for (const name of fs.readdirSync(absolute).sort()) {
        visit(path.posix.join(relative, name));
      }
    } else {
      files[relative] = crypto.createHash('sha256')
        .update(fs.readFileSync(absolute)).digest('hex');
    }
  }
  entries.forEach(visit);
  return files;
}

function inputFingerprint(root) {
  return fingerprintFiles(root, INPUTS);
}

function outputFingerprint(root) {
  const dist = path.join(root, 'dist');
  if (!fs.statSync(path.join(dist, 'index.html')).isFile()
      || fs.statSync(path.join(dist, 'index.html')).size === 0) {
    throw new Error('Frontend build entry is missing or empty');
  }
  return fingerprintFiles(dist, ['.'], new Set([STATE_NAME]));
}

function same(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function recordBuild(root, inputs) {
  if (!same(inputs, inputFingerprint(root))) {
    throw new Error('Frontend build inputs changed during build; rebuild required');
  }
  const state = { version: 1, inputs, outputs: outputFingerprint(root) };
  fs.writeFileSync(path.join(root, 'dist', STATE_NAME), JSON.stringify(state));
}

function isBuildCurrent(root) {
  try {
    const state = JSON.parse(fs.readFileSync(path.join(root, 'dist', STATE_NAME), 'utf8'));
    return state.version === 1
      && same(state.inputs, inputFingerprint(root))
      && same(state.outputs, outputFingerprint(root));
  } catch {
    return false;
  }
}

module.exports = { STATE_NAME, inputFingerprint, recordBuild, isBuildCurrent };

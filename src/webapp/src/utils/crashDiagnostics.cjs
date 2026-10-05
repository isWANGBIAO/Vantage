const fs = require('fs');
const path = require('path');
const { randomUUID } = require('crypto');

const MAX_RECORDS = 10;
const MAX_BYTES = 200 * 1024 * 1024;
const NATIVE_WRITE_GRACE_MS = 30000;
const EXIT_REASONS = new Set(['crashed', 'oom', 'killed', 'abnormal-exit', 'launch-failed', 'integrity-failure']);
const PROCESS_TYPES = new Set(['renderer', 'backend', 'child', 'main']);

function defaultIsPidAlive(pid) {
  if (!Number.isSafeInteger(pid) || pid <= 0) return false;
  try { process.kill(pid, 0); return true; } catch (error) { return error.code !== 'ESRCH'; }
}

function createCrashDiagnostics({
  dataDir,
  pid = process.pid,
  isPidAlive = defaultIsPidAlive,
  maxRecords = MAX_RECORDS,
  maxBytes = MAX_BYTES,
  now = Date.now,
} = {}) {
  const directory = path.resolve(dataDir, 'diagnostics');
  const electronDirectory = path.join(directory, 'electron');
  const markerPath = path.join(directory, 'electron-session.active.json');
  const sessionId = randomUUID();
  let previousInterrupted = false;
  let available = true;
  let nativeCollector = false;
  let ownsMarker = false;
  let shuttingDown = false;
  let timer;

  function ensureDirectory(relative = '') {
    // Never follow a symlink/junction within the diagnostics tree.
    let current = directory;
    for (const part of ['', ...relative.split(path.sep).filter(Boolean)]) {
      if (part) current = path.join(current, part);
      if (!fs.existsSync(current)) fs.mkdirSync(current);
      const stat = fs.lstatSync(current);
      if (stat.isSymbolicLink() || !stat.isDirectory()) throw new Error('Unsafe diagnostics directory');
    }
    return current;
  }

  function safeRun(operation, fallback = false) {
    try { return operation(); } catch { available = false; return fallback; }
  }

  function getStatus() {
    return { localOnly: true, directory, previousInterrupted, available, nativeCollector,
      retention: { maxRecords, maxBytes } };
  }

  function lstatOrNull(filename) {
    try { return fs.lstatSync(filename); } catch (error) { if (error.code === 'ENOENT') return null; throw error; }
  }

  function startNativeCollector({ app, crashReporter }) {
    return safeRun(() => {
      ensureDirectory('electron');
      app.setPath('crashDumps', electronDirectory);
      crashReporter.start({ uploadToServer: false, ignoreSystemCrashHandler: true, compress: true });
      nativeCollector = true;
      return true;
    });
  }

  function readMarker() {
    if (!fs.existsSync(markerPath)) return null;
    const stat = fs.lstatSync(markerPath);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 4096) throw new Error('Unsafe session marker');
    return JSON.parse(fs.readFileSync(markerPath, 'utf8'));
  }

  function startSession() {
    return safeRun(() => {
      ensureDirectory();
      const prior = readMarker();
      if (prior && isPidAlive(prior.pid)) return false;
      if (prior) {
        previousInterrupted = true;
        fs.unlinkSync(markerPath);
        recordExit('main', { reason: 'abnormal-exit' });
      }
      fs.writeFileSync(markerPath, JSON.stringify({ pid, sessionId, startedAt: new Date(now()).toISOString() }), { flag: 'wx', mode: 0o600 });
      ownsMarker = true;
      cleanup();
      return true;
    });
  }

  function collectReports() {
    const reports = [];
    function walk(parent, depth) {
      if (depth > 8) return;
      for (const name of fs.readdirSync(parent)) {
        const filename = path.join(parent, name);
        const stat = lstatOrNull(filename);
        if (!stat) continue;
        if (stat.isSymbolicLink()) continue;
        if (stat.isDirectory()) { walk(filename, depth + 1); continue; }
        if (!stat.isFile() || !(/\.(dmp|log)$/i.test(name) || /^incident-.*\.json$/.test(name))) continue;
        if (filename === markerPath) continue;
        // POSIX Crashpad writes in new/, then moves closed reports to pending/.
        // Windows uses reports/ while writing, with DELETE sharing disabled.
        const nativeWriting = /\.dmp$/i.test(name) && (path.relative(directory, filename).split(path.sep).includes('new') || now() - stat.mtimeMs < NATIVE_WRITE_GRACE_MS);
        const active = /\.active\./.test(name) || nativeWriting;
        reports.push({ filename, size: stat.size, mtimeMs: stat.mtimeMs, dev: stat.dev, ino: stat.ino, active });
      }
    }
    ensureDirectory();
    walk(directory, 0);
    return reports;
  }

  function cleanup() {
    return safeRun(() => {
      const reports = collectReports();
      let totalBytes = reports.reduce((sum, report) => sum + report.size, 0);
      const completed = reports.filter(report => !report.active).sort((a, b) => a.mtimeMs - b.mtimeMs);
      let completedRecords = completed.length;
      for (const report of completed) {
        if (completedRecords <= maxRecords && totalBytes <= maxBytes) break;
        // Recheck for writers/path replacement immediately before deletion.
        if (!hasSafeParents(report.filename)) continue;
        const current = lstatOrNull(report.filename);
        if (!current) { completedRecords -= 1; totalBytes -= report.size; continue; }
        if (!current.isFile() || current.isSymbolicLink() || current.size !== report.size || current.mtimeMs !== report.mtimeMs || current.dev !== report.dev || current.ino !== report.ino) continue;
        try { fs.unlinkSync(report.filename); } catch (error) {
          if (/\.dmp$/i.test(report.filename) && ['EPERM', 'EBUSY', 'EACCES'].includes(error.code)) continue;
          if (error.code !== 'ENOENT') throw error;
        }
        completedRecords -= 1;
        totalBytes -= report.size;
      }
      return { completedRecords, totalBytes, overBudget: totalBytes > maxBytes || completedRecords > maxRecords };
    }, { completedRecords: 0, totalBytes: 0, overBudget: false });
  }

  function hasSafeParents(filename) {
    const relative = path.relative(directory, filename);
    if (relative.startsWith(`..${path.sep}`) || relative === '..' || path.isAbsolute(relative)) return false;
    let current = directory;
    for (const part of ['', ...path.dirname(relative).split(path.sep).filter(part => part && part !== '.')]) {
      if (part) current = path.join(current, part);
      const stat = lstatOrNull(current);
      if (!stat || stat.isSymbolicLink() || !stat.isDirectory()) return false;
    }
    return true;
  }

  function recordExit(processType, details = {}) {
    if (shuttingDown || details.reason === 'clean-exit') return false;
    return safeRun(() => {
      const target = ensureDirectory('incidents');
      const incident = {
        recordedAt: new Date(now()).toISOString(),
        sessionId,
        processType: PROCESS_TYPES.has(processType) ? processType : 'child',
        reason: EXIT_REASONS.has(details.reason) ? details.reason : 'abnormal-exit',
        exitCode: Number.isSafeInteger(details.exitCode) ? details.exitCode : null,
      };
      // Never persist child service names, error messages, exception values or args.
      fs.writeFileSync(path.join(target, `incident-${now()}-${randomUUID()}.json`), JSON.stringify(incident, null, 2), { flag: 'wx', mode: 0o600 });
      cleanup();
      return true;
    });
  }

  function observeBackend(child) {
    if (!child || typeof child.once !== 'function') return;
    let recorded = false;
    const recordOnce = details => {
      if (recorded) return;
      recorded = true;
      recordExit('backend', details);
    };
    child.once('exit', (code, signal) => {
      if (code !== 0 || signal) recordOnce({ reason: 'abnormal-exit', exitCode: code });
    });
    child.once('error', () => recordOnce({ reason: 'launch-failed' }));
  }

  function beginShutdown() { shuttingDown = true; }

  function markClean() {
    shuttingDown = true;
    if (timer) clearInterval(timer);
    return safeRun(() => {
      if (!ownsMarker) return false;
      const current = readMarker();
      if (current?.sessionId !== sessionId) return false;
      fs.unlinkSync(markerPath);
      ownsMarker = false;
      cleanup();
      return true;
    });
  }

  function startPeriodicCleanup() {
    if (timer) return;
    timer = setInterval(cleanup, 60000);
    timer.unref();
  }

  function installIpc({ ipcMain, getWebContents, isTrustedSender, shell }) {
    function authorize(event, args) {
      if (!event || event.sender !== getWebContents() || !isTrustedSender(event)) throw new Error('Unauthorized diagnostics access');
      if (args.length) throw new Error('Diagnostics operations accept no arguments');
    }
    ipcMain.handle('diagnostics:get-status', (event, ...args) => { authorize(event, args); return getStatus(); });
    ipcMain.handle('diagnostics:open-directory', async (event, ...args) => {
      authorize(event, args);
      if (!safeRun(() => { ensureDirectory(); return true; })) return { opened: false };
      try { return { opened: (await shell.openPath(directory)) === '' }; } catch { return { opened: false }; }
    });
  }

  return { getStatus, startNativeCollector, startSession, cleanup, recordExit, observeBackend,
    beginShutdown, markClean, startPeriodicCleanup, installIpc };
}

module.exports = { createCrashDiagnostics, MAX_RECORDS, MAX_BYTES };

const fs = require('fs');
const path = require('path');
const { randomUUID } = require('crypto');
const { verifiedIdentity } = require('./desktopLaunch.cjs');

const MAX_RECORDS = 10;
const MAX_BYTES = 200 * 1024 * 1024;
const NATIVE_WRITE_GRACE_MS = 30000;
const EXIT_REASONS = new Set(['crashed', 'oom', 'killed', 'abnormal-exit', 'launch-failed', 'integrity-failure']);
const PROCESS_TYPES = new Set(['renderer', 'backend', 'child', 'main']);
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX_LIFECYCLE_RECORDS = 100;
const MAX_LIFECYCLE_BYTES = 5 * 1024 * 1024;
const MAX_OLD_SESSIONS = 20;
const HEARTBEAT_MS = 5000;
const RENAME_RETRY_CODES = new Set(['EPERM', 'EACCES', 'EBUSY']);
const RENAME_RETRY_WAIT = new Int32Array(new SharedArrayBuffer(4));
const validPid = value => Number.isSafeInteger(value) && value > 0 && value <= 0xffffffff;
const validTime = value => typeof value === 'string' && value.length <= 32 && Number.isFinite(Date.parse(value)) && new Date(value).toISOString() === value;

function defaultIsPidAlive(pid) {
  if (!Number.isSafeInteger(pid) || pid <= 0) return false;
  try { process.kill(pid, 0); return true; } catch (error) { return error.code !== 'ESRCH'; }
}

function createCrashDiagnostics({
  dataDir,
  pid = process.pid,
  parentPid = process.ppid,
  launchIdentity = null,
  isPidAlive = defaultIsPidAlive,
  isSessionAlive = prior => isPidAlive(prior.pid),
  maxRecords = MAX_RECORDS,
  maxBytes = MAX_BYTES,
  now = Date.now,
  onFailure = () => {},
} = {}) {
  const directory = path.resolve(dataDir, 'diagnostics');
  const electronDirectory = path.join(directory, 'electron');
  const markerPath = path.join(directory, 'electron-session.active.json');
  const sessionId = randomUUID();
  const sessionPath = path.join(directory, 'sessions', `${sessionId}.active.json`);
  let state = null;
  let lastCleanupAt = 0;
  let previousInterrupted = false;
  let available = true;
  let nativeCollector = false;
  let ownsMarker = false;
  let shuttingDown = false;
  let timer;
  let retentionWarning = false;

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
    try { return operation(); } catch {
      if (available) { try { onFailure('storage-unavailable'); } catch { /* Diagnostics must not crash the app. */ } }
      available = false;
      return fallback;
    }
  }

  function getStatus() {
    return { localOnly: true, directory, previousInterrupted, available, nativeCollector,
      retention: { maxRecords, maxBytes }, observerStatus: state?.observerStatus ?? null };
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

  function readMarker({ allowCorrupt = false, withSnapshot = false } = {}) {
    if (!fs.existsSync(markerPath)) return null;
    const stat = fs.lstatSync(markerPath);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('Unsafe session marker');
    const text = stat.size <= 4096 ? fs.readFileSync(markerPath, 'utf8') : null;
    let value;
    try {
      if (text === null) throw new Error('Oversized session marker');
      value = sanitizeSession(JSON.parse(text));
    } catch (error) {
      if (!allowCorrupt) throw error;
      return { value: null, stat, corrupt: true };
    }
    return withSnapshot ? { value, stat, corrupt: false } : value;
  }

  function sanitizeSession(value) {
    if (!value || !validPid(value.pid) || !UUID_PATTERN.test(value.sessionId) || !validTime(value.startedAt)) throw new Error('Invalid session identity');
    if (value.lastHeartbeatAt != null && !validTime(value.lastHeartbeatAt)) throw new Error('Invalid heartbeat');
    if (value.backendStartedAt != null && !validTime(value.backendStartedAt)) throw new Error('Invalid backend time');
    return {
      schemaVersion: 1, sessionId: value.sessionId, pid: value.pid,
      parentPid: validPid(value.parentPid) ? value.parentPid : null,
      startedAt: value.startedAt, lastHeartbeatAt: value.lastHeartbeatAt || value.startedAt,
      phase: ['running', 'shutting-down', 'clean'].includes(value.phase) ? value.phase : 'running',
      backendPid: validPid(value.backendPid) ? value.backendPid : null,
      backendStartedAt: value.backendStartedAt || null,
      launchIdentity: verifiedIdentity(value.launchIdentity, value.pid),
      observerStatus: sanitizeObserver(value.observerStatus),
    };
  }

  function sanitizeObserver(value = {}) {
    return {
      status: ['not-started', 'starting', 'ready', 'failed', 'unsupported', 'stopped'].includes(value?.status) ? value.status : 'not-started',
      isolation: ['unknown', 'breakaway', 'detached', 'degraded', 'unsupported', 'inherited-job', 'desktop-independent'].includes(value?.isolation) ? value.isolation : 'unknown',
      pid: validPid(value?.pid) ? value.pid : null,
      ...(verifiedIdentity(value?.identity, value?.pid) ? { identity: verifiedIdentity(value.identity, value.pid) } : {}),
    };
  }

  function writeDurableJson(filename, value, { atomic = false, exclusive = false } = {}) {
    if (!hasSafeParents(filename)) throw new Error('Unsafe diagnostics parent');
    const existing = lstatOrNull(filename);
    if (existing && (!existing.isFile() || existing.isSymbolicLink())) throw new Error('Unsafe diagnostics file');
    const temporary = atomic ? path.join(path.dirname(filename), `.tmp-${randomUUID()}`) : filename;
    let descriptor;
    try {
      descriptor = fs.openSync(temporary, 'wx', 0o600);
      fs.writeFileSync(descriptor, JSON.stringify(value, null, 2));
      fs.fsyncSync(descriptor);
      fs.closeSync(descriptor); descriptor = undefined;
      if (atomic) {
        // A first publication must not replace another owner's concurrently
        // published marker. Hard-link creation is atomic and fails on EEXIST.
        if (exclusive) fs.linkSync(temporary, filename);
        else renameWithBriefRetry(temporary, filename);
      }
      if (process.platform !== 'win32') {
        const parent = fs.openSync(path.dirname(filename), 'r');
        try { fs.fsyncSync(parent); } finally { fs.closeSync(parent); }
      }
    } finally {
      if (descriptor !== undefined) fs.closeSync(descriptor);
      if (atomic && fs.existsSync(temporary)) fs.unlinkSync(temporary);
    }
  }

  function renameWithBriefRetry(source, destination) {
    const started = process.hrtime.bigint();
    for (let attempt = 0; ; attempt += 1) {
      try { fs.renameSync(source, destination); return; }
      catch (error) {
        const remaining = 50 - Number(process.hrtime.bigint() - started) / 1e6;
        // An observer may briefly hold the target on Windows. Cap both the
        // attempt count and elapsed budget; real storage failures still surface.
        if (!RENAME_RETRY_CODES.has(error.code) || attempt >= 11 || remaining <= 2) throw error;
        Atomics.wait(RENAME_RETRY_WAIT, 0, 0, Math.min(4, remaining - 1));
      }
    }
  }

  function writeState() {
    if (!ownsMarker || !state) return false;
    if (readMarker()?.sessionId !== sessionId) return false;
    writeDurableJson(sessionPath, state, { atomic: true });
    writeDurableJson(markerPath, state, { atomic: true });
    return true;
  }

  function getObserverSession() {
    return ownsMarker && state ? { sessionId, sessionPath } : null;
  }

  function heartbeat() {
    return safeRun(() => {
      if (!state || !ownsMarker || state.phase === 'clean') return false;
      state.lastHeartbeatAt = new Date(now()).toISOString();
      return writeState();
    });
  }

  function setObserverStatus(value) {
    return safeRun(() => {
      if (!state || !ownsMarker) return false;
      state.observerStatus = sanitizeObserver(value);
      return writeState();
    });
  }

  function writeLifecycle(processType, details = {}, identity = state) {
    const target = ensureDirectory('lifecycle');
    const stamp = new Date(now()).toISOString();
    const info = identity || { sessionId, pid, parentPid, phase: shuttingDown ? 'shutting-down' : 'running' };
    const recovered = details.source === 'recovery';
    const event = {
      schemaVersion: 1, recordedAt: stamp, sessionId: info.sessionId,
      processType: PROCESS_TYPES.has(processType) ? processType : 'child',
      pid: validPid(details.pid) ? details.pid : (processType === 'main' && validPid(info.pid) ? info.pid : null),
      parentPid: processType === 'backend' ? (validPid(info.pid) ? info.pid : null) : (validPid(info.parentPid) ? info.parentPid : null),
      startedAt: (processType === 'main' ? info.startedAt : (processType === 'backend' ? info.backendStartedAt : null)) || null,
      lastHeartbeatAt: info.lastHeartbeatAt || null,
      phase: info.phase, source: recovered ? 'recovery' : 'main',
      reason: ['interrupted', 'corrupt-marker', 'clean-exit', ...EXIT_REASONS].includes(details.reason) ? details.reason : 'abnormal-exit',
      exitCode: Number.isSafeInteger(details.exitCode) ? details.exitCode : null,
      signal: ['SIGTERM', 'SIGKILL', 'SIGINT', 'SIGABRT', 'SIGSEGV'].includes(details.signal) ? details.signal : null,
      observedAt: recovered ? null : stamp,
      ...(recovered ? { detectedAt: stamp } : {}),
    };
    writeDurableJson(path.join(target, `exit-${now()}-${randomUUID()}.json`), event);
    cleanupLifecycle();
    return true;
  }

  function startSession() {
    return safeRun(() => {
      ensureDirectory();
      ensureDirectory('sessions');
      ensureDirectory('lifecycle');
      const marker = readMarker({ allowCorrupt: true, withSnapshot: true });
      const prior = marker?.value;
      if (prior && isSessionAlive(prior) !== false) return false;
      if (marker) {
        previousInterrupted = true;
        if (marker.corrupt) {
          writeLifecycle('main', { reason: 'corrupt-marker', source: 'recovery' }, { sessionId: null, pid: null, parentPid: null, phase: 'unknown' });
        } else {
          writeIncident('main', { reason: 'abnormal-exit' }, prior);
          writeLifecycle('main', { reason: 'interrupted', source: 'recovery' }, prior);
        }
        if (!hasSafeParents(markerPath) || !sameFileSnapshot(lstatOrNull(markerPath), marker.stat)) return false;
        fs.unlinkSync(markerPath);
      }
      const stamp = new Date(now()).toISOString();
      state = sanitizeSession({ pid, parentPid, launchIdentity, sessionId, startedAt: stamp, lastHeartbeatAt: stamp, phase: 'running' });
      writeDurableJson(sessionPath, state, { atomic: true, exclusive: true });
      writeDurableJson(markerPath, state, { atomic: true, exclusive: true });
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
      cleanupLifecycle();
      return { completedRecords, totalBytes, overBudget: totalBytes > maxBytes || completedRecords > maxRecords };
    }, { completedRecords: 0, totalBytes: 0, overBudget: false });
  }

  function pruneSnapshots(files, maxCount, maxSize) {
    let bytes = files.reduce((total, item) => total + item.stat.size, 0);
    let count = files.length;
    files.sort((a, b) => a.stat.mtimeMs - b.stat.mtimeMs);
    for (const item of files) {
      if (count <= maxCount && bytes <= maxSize) break;
      if (!hasSafeParents(item.filename)) continue;
      const current = lstatOrNull(item.filename);
      if (!current) { count -= 1; bytes -= item.stat.size; continue; }
      if (!current.isFile() || current.isSymbolicLink() || current.ino !== item.stat.ino || current.dev !== item.stat.dev || current.size !== item.stat.size || current.mtimeMs !== item.stat.mtimeMs) continue;
      fs.unlinkSync(item.filename); count -= 1; bytes -= item.stat.size;
    }
  }

  function sameFileSnapshot(current, expected) {
    return current?.isFile() && !current.isSymbolicLink() && current.dev === expected.dev && current.ino === expected.ino && current.size === expected.size && current.mtimeMs === expected.mtimeMs;
  }

  function liveSession(snapshot) {
    // Identity probing may spawn a native helper. Retention runs on Electron's
    // event loop, so conservatively preserve any live PID without that probe.
    return isPidAlive(snapshot.pid)
      || (validPid(snapshot.backendPid) && isPidAlive(snapshot.backendPid))
      || (validPid(snapshot.observerStatus.pid) && isPidAlive(snapshot.observerStatus.pid));
  }

  function cleanupLifecycle() {
    const protectedIds = new Set([sessionId]);
    let overBudget = false;
    const sessions = lstatOrNull(path.join(directory, 'sessions'));
    if (sessions) {
      ensureDirectory('sessions');
      const files = []; const protectedFiles = [];
      for (const name of fs.readdirSync(path.join(directory, 'sessions'))) {
        const identity = name.replace(/\.active\.json$/, '');
        if (!UUID_PATTERN.test(identity) || !name.endsWith('.active.json')) continue;
        const filename = path.join(directory, 'sessions', name);
        const stat = lstatOrNull(filename);
        if (!stat?.isFile() || stat.isSymbolicLink()) continue;
        const item = { filename, stat };
        if (identity === sessionId) { protectedFiles.push(item); continue; }
        let snapshot;
        try {
          if (stat.size > 16384) throw new Error('Oversized session snapshot');
          snapshot = sanitizeSession(JSON.parse(fs.readFileSync(filename, 'utf8')));
        } catch {
          protectedIds.add(identity); protectedFiles.push(item); continue;
        } // Unknown historical identity: preserve without disabling live evidence.
        if (liveSession(snapshot)) { protectedIds.add(identity); protectedFiles.push(item); }
        else files.push(item);
      }
      const activeBytes = protectedFiles.reduce((total, item) => total + item.stat.size, 0);
      overBudget ||= protectedFiles.length > MAX_OLD_SESSIONS + 1 || activeBytes > MAX_LIFECYCLE_BYTES;
      pruneSnapshots(files, Math.max(0, MAX_OLD_SESSIONS + 1 - protectedFiles.length), Math.max(0, MAX_LIFECYCLE_BYTES - activeBytes));
    }
    const lifecycle = lstatOrNull(path.join(directory, 'lifecycle'));
    if (lifecycle) {
      ensureDirectory('lifecycle');
      const files = []; const protectedFiles = [];
      for (const name of fs.readdirSync(path.join(directory, 'lifecycle'))) {
        if (!/^(exit-|watcher-).+\.json$/.test(name)) continue;
        const filename = path.join(directory, 'lifecycle', name); const stat = lstatOrNull(filename);
        if (!stat?.isFile() || stat.isSymbolicLink()) continue;
        const item = { filename, stat };
        const watcherId = name.startsWith('watcher-') ? name.slice(8, -5) : null;
        let liveWatcher = false;
        if (watcherId && stat.size <= 4096) {
          try { const ack = JSON.parse(fs.readFileSync(filename, 'utf8')); liveWatcher = validPid(ack.pid) && isPidAlive(ack.pid); }
          catch { /* No usable live identity in a malformed acknowledgement. */ }
        }
        if (watcherId && (protectedIds.has(watcherId) || liveWatcher)) protectedFiles.push(item);
        else files.push(item);
      }
      const activeBytes = protectedFiles.reduce((total, item) => total + item.stat.size, 0);
      overBudget ||= protectedFiles.length > MAX_LIFECYCLE_RECORDS || activeBytes > MAX_LIFECYCLE_BYTES;
      pruneSnapshots(files, Math.max(0, MAX_LIFECYCLE_RECORDS - protectedFiles.length), Math.max(0, MAX_LIFECYCLE_BYTES - activeBytes));
    }
    if (overBudget && !retentionWarning) { try { onFailure('retention-active-over-budget'); } catch { /* Metadata-only warning. */ } }
    retentionWarning = overBudget;
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
      writeIncident(processType, details, state || { sessionId, pid });
      writeLifecycle(processType, details);
      cleanup();
      return true;
    });
  }

  function writeIncident(processType, details, identity) {
      const target = ensureDirectory('incidents');
      const incident = {
        recordedAt: new Date(now()).toISOString(),
        sessionId: identity.sessionId,
        pid: validPid(details.pid) ? details.pid : (processType === 'main' ? identity.pid : null),
        startedAt: (processType === 'main' ? identity.startedAt : (processType === 'backend' ? identity.backendStartedAt : null)) || null,
        lastHeartbeatAt: identity.lastHeartbeatAt || null,
        processType: PROCESS_TYPES.has(processType) ? processType : 'child',
        reason: EXIT_REASONS.has(details.reason) ? details.reason : 'abnormal-exit',
        exitCode: Number.isSafeInteger(details.exitCode) ? details.exitCode : null,
      };
      // Never persist child service names, error messages, exception values or args.
      writeDurableJson(path.join(target, `incident-${now()}-${randomUUID()}.json`), incident);
  }

  function observeBackend(child) {
    if (!child || typeof child.once !== 'function') return;
    if (state && validPid(child.pid)) safeRun(() => {
      state.backendPid = child.pid;
      state.backendStartedAt = new Date(now()).toISOString();
      writeState();
    });
    let recorded = false;
    const recordOnce = details => {
      if (recorded) return;
      recorded = true;
      if (shuttingDown) safeRun(() => writeLifecycle('backend', { ...details, reason: 'clean-exit', pid: child.pid }));
      else recordExit('backend', { ...details, pid: child.pid });
    };
    child.once('exit', (code, signal) => {
      recordOnce({ reason: 'abnormal-exit', exitCode: code, signal });
    });
    child.once('error', () => recordOnce({ reason: 'launch-failed' }));
  }

  function beginShutdown() {
    shuttingDown = true;
    return safeRun(() => { if (!state) return false; state.phase = 'shutting-down'; return writeState(); });
  }

  function markClean() {
    shuttingDown = true;
    if (timer) clearInterval(timer);
    return safeRun(() => {
      if (!ownsMarker) return false;
      const current = readMarker();
      if (current?.sessionId !== sessionId) return false;
      state.phase = 'clean';
      state.lastHeartbeatAt = new Date(now()).toISOString();
      writeDurableJson(sessionPath, state, { atomic: true });
      writeLifecycle('main', { reason: 'clean-exit', exitCode: 0 });
      fs.unlinkSync(markerPath);
      ownsMarker = false;
      cleanup();
      return true;
    });
  }

  function startPeriodicCleanup() {
    if (timer) return;
    lastCleanupAt = now();
    timer = setInterval(() => {
      heartbeat();
      if (now() - lastCleanupAt >= 60000) { cleanup(); lastCleanupAt = now(); }
    }, HEARTBEAT_MS);
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
    beginShutdown, markClean, startPeriodicCleanup, installIpc, getObserverSession, heartbeat, setObserverStatus };
}

module.exports = { createCrashDiagnostics, MAX_RECORDS, MAX_BYTES };

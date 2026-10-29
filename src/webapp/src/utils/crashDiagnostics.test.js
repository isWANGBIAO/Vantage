import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { EventEmitter } from 'node:events';
import process from 'node:process';
import { Buffer } from 'node:buffer';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
let diagnostics;
try { diagnostics = require('./crashDiagnostics.cjs'); } catch { diagnostics = {}; }
function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-diagnostics-test-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}
function create(dataDir, extra = {}) {
  return diagnostics.createCrashDiagnostics({ dataDir, pid: 12345, isPidAlive: () => false, ...extra });
}
function writeReport(root, filename, size, age = 60000) {
  const target = path.join(root, filename);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, Buffer.alloc(size));
  const stamp = new Date(Date.now() - age);
  fs.utimesSync(target, stamp, stamp);
  return target;
}

function lifecycleRecords(root) {
  const dir = path.join(root, 'diagnostics', 'lifecycle');
  return fs.existsSync(dir) ? fs.readdirSync(dir).filter(name => name.endsWith('.json')).map(name => JSON.parse(fs.readFileSync(path.join(dir, name), 'utf8'))) : [];
}

test('durable session snapshots track heartbeat, backend, observer and shutdown phase', t => {
  const root = fixture(t);
  let clock = Date.parse('2026-01-01T00:00:00Z');
  const collector = create(root, { parentPid: 678, now: () => clock });
  assert.equal(collector.startSession(), true);
  const handle = collector.getObserverSession();
  let value = JSON.parse(fs.readFileSync(handle.sessionPath, 'utf8'));
  assert.equal(value.schemaVersion, 1);
  assert.equal(value.pid, 12345);
  assert.equal(value.parentPid, 678);
  assert.equal(value.phase, 'running');
  assert.equal(value.backendPid, null);
  assert.equal(value.sessionId, handle.sessionId);
  clock += 5000;
  assert.equal(collector.heartbeat(), true);
  const child = new EventEmitter(); child.pid = 54321;
  collector.observeBackend(child);
  assert.equal(collector.setObserverStatus({ status: 'ready', isolation: 'breakaway', pid: 987, secret: 'must-not-save' }), true);
  value = JSON.parse(fs.readFileSync(handle.sessionPath, 'utf8'));
  assert.equal(value.backendPid, 54321);
  assert.equal(value.backendStartedAt, '2026-01-01T00:00:05.000Z');
  assert.equal(value.lastHeartbeatAt, '2026-01-01T00:00:05.000Z');
  assert.deepEqual(value.observerStatus, { status: 'ready', isolation: 'breakaway', pid: 987 });
  collector.beginShutdown();
  assert.equal(JSON.parse(fs.readFileSync(handle.sessionPath)).phase, 'shutting-down');
  assert.equal(collector.markClean(), true);
  assert.equal(JSON.parse(fs.readFileSync(handle.sessionPath)).phase, 'clean');
  assert.equal(fs.existsSync(path.join(root, 'diagnostics', 'electron-session.active.json')), false);
  assert.ok(lifecycleRecords(root).some(event => event.processType === 'main' && event.reason === 'clean-exit' && event.exitCode === 0));
});

test('recovery preserves interrupted identity and separates discovery from unknown exit time', t => {
  const root = fixture(t);
  let clock = Date.parse('2026-01-01T00:00:00Z');
  const first = create(root, { now: () => clock }); first.startSession();
  const old = first.getObserverSession();
  clock += 5000; first.heartbeat();
  clock += 100000;
  const second = create(root, { pid: 22222, now: () => clock }); second.startSession();
  const recovered = lifecycleRecords(root).find(event => event.source === 'recovery');
  assert.equal(recovered.sessionId, old.sessionId);
  assert.equal(recovered.pid, 12345);
  assert.equal(recovered.lastHeartbeatAt, '2026-01-01T00:00:05.000Z');
  assert.equal(recovered.detectedAt, new Date(clock).toISOString());
  assert.equal(recovered.observedAt, null);
  assert.equal(recovered.reason, 'interrupted');
  const incidentDir = path.join(root, 'diagnostics', 'incidents');
  const incident = JSON.parse(fs.readFileSync(path.join(incidentDir, fs.readdirSync(incidentDir)[0])));
  assert.equal(incident.sessionId, old.sessionId);
  assert.equal(incident.pid, 12345);
  second.markClean();
});

test('backend code zero is unexpected unless intentional shutdown has started', t => {
  const root = fixture(t); const collector = create(root); collector.startSession();
  const first = new EventEmitter(); first.pid = 555; collector.observeBackend(first);
  first.emit('exit', 0, null); first.emit('exit', 0, null);
  let events = lifecycleRecords(root).filter(event => event.processType === 'backend');
  assert.equal(events.length, 1); assert.equal(events[0].reason, 'abnormal-exit'); assert.equal(events[0].exitCode, 0);
  const incidentDir = path.join(root, 'diagnostics', 'incidents');
  const incident = JSON.parse(fs.readFileSync(path.join(incidentDir, fs.readdirSync(incidentDir)[0])));
  assert.equal(incident.pid, 555);
  const second = new EventEmitter(); second.pid = 556; collector.observeBackend(second);
  collector.beginShutdown(); second.emit('exit', 15, null);
  events = lifecycleRecords(root).filter(event => event.processType === 'backend');
  assert.equal(events.length, 2); assert.ok(events.some(event => event.reason === 'clean-exit' && event.exitCode === 15));
  collector.markClean();
});

test('unsafe previous markers are not overwritten and failures report only enums', t => {
  const root = fixture(t); const dir = path.join(root, 'diagnostics'); fs.mkdirSync(dir);
  const marker = path.join(dir, 'electron-session.active.json');
  const text = JSON.stringify({ pid: 123, sessionId: '../private-secret', startedAt: 'arbitrary-private-value' });
  fs.writeFileSync(marker, text);
  const failures = []; const collector = create(root, { onFailure: code => failures.push(code) });
  assert.equal(collector.startSession(), false);
  assert.equal(fs.readFileSync(marker, 'utf8'), text);
  assert.deepEqual(failures, ['storage-unavailable']);
  assert.equal(collector.getStatus().available, false);
});

test('heartbeat never steals another session marker', t => {
  const root = fixture(t); const first = create(root); first.startSession();
  const second = create(root); second.startSession();
  const owned = second.getObserverSession();
  assert.equal(first.heartbeat(), false);
  assert.equal(JSON.parse(fs.readFileSync(path.join(root, 'diagnostics', 'electron-session.active.json'))).sessionId, owned.sessionId);
  second.markClean();
});

test('lifecycle retention is separate, bounded and never follows session junctions', t => {
  const root = fixture(t); const outside = fixture(t);
  const external = writeReport(outside, 'preserved.json', 5);
  const dir = path.join(root, 'diagnostics'); fs.mkdirSync(path.join(dir, 'lifecycle'), { recursive: true });
  fs.symlinkSync(outside, path.join(dir, 'sessions'), process.platform === 'win32' ? 'junction' : 'dir');
  const bad = create(root); assert.equal(bad.startSession(), false);
  assert.equal(fs.existsSync(external), true);
  fs.unlinkSync(path.join(dir, 'sessions'));
  const collector = create(root); collector.startSession();
  for (let index = 0; index < 110; index += 1) writeReport(dir, `lifecycle/exit-old-${index}.json`, 5, 120000 + index);
  collector.cleanup();
  assert.equal(fs.readdirSync(path.join(dir, 'lifecycle')).length, 100);
  collector.markClean();
});

test('old session history is bounded and a malformed old snapshot does not stop a new session', t => {
  const root = fixture(t);
  for (let index = 0; index < 24; index += 1) {
    const collector = create(root); assert.equal(collector.startSession(), true); collector.markClean();
  }
  const sessions = path.join(root, 'diagnostics', 'sessions');
  assert.ok(fs.readdirSync(sessions).length <= 21);
  fs.writeFileSync(path.join(sessions, '11111111-1111-1111-1111-111111111111.active.json'), '{broken');
  const collector = create(root);
  assert.equal(collector.startSession(), true);
  assert.equal(collector.getStatus().available, true);
  assert.equal(collector.heartbeat(), true);
  collector.markClean();
});

test('killing the only evidence writer leaves its durable session recoverable', async t => {
  const root = fixture(t);
  const modulePath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), 'crashDiagnostics.cjs');
  const script = `const {createCrashDiagnostics}=require(${JSON.stringify(modulePath)});const d=createCrashDiagnostics({dataDir:${JSON.stringify(root)}});if(!d.startSession())process.exit(2);d.heartbeat();console.log('ready');setInterval(()=>{},1000);`;
  const child = spawn(process.execPath, ['-e', script], { stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
  t.after(() => { if (child.exitCode === null) child.kill(); });
  const exited = once(child, 'exit');
  await once(child.stdout, 'data');
  const old = JSON.parse(fs.readFileSync(path.join(root, 'diagnostics', 'electron-session.active.json')));
  child.kill(); await exited;
  const recovered = create(root);
  assert.equal(recovered.startSession(), true);
  const event = lifecycleRecords(root).find(value => value.source === 'recovery');
  assert.equal(event.sessionId, old.sessionId);
  assert.equal(event.pid, child.pid);
  assert.equal(event.lastHeartbeatAt, old.lastHeartbeatAt);
  assert.equal(event.observedAt, null);
  recovered.markClean();
});

test('starts local-only Crashpad in configured data root before starting a session', t => {
  const dataDir = fixture(t);
  const calls = [];
  const collector = create(dataDir);
  collector.startNativeCollector({ app: { setPath: (...args) => calls.push(args) }, crashReporter: { start: options => calls.push(options) } });
  assert.deepEqual(calls[0], ['crashDumps', path.join(dataDir, 'diagnostics', 'electron')]);
  assert.deepEqual(calls[1], { uploadToServer: false, ignoreSystemCrashHandler: true, compress: true });
  assert.equal(collector.getStatus().localOnly, true);
  assert.deepEqual(collector.getStatus().retention, { maxRecords: 10, maxBytes: 209715200 });
});

test('interrupted marker is recovered on next start and clean quit does not warn', t => {
  const root = fixture(t);
  const first = create(root);
  first.startSession();
  const second = create(root);
  second.startSession();
  assert.equal(second.getStatus().previousInterrupted, true);
  second.markClean();
  const third = create(root);
  third.startSession();
  assert.equal(third.getStatus().previousInterrupted, false);
  third.markClean();
});

test('a live previous marker is not overwritten and no false interruption is claimed', t => {
  const root = fixture(t);
  create(root).startSession();
  const collector = create(root, { isPidAlive: () => true });
  assert.equal(collector.startSession(), false);
  assert.equal(collector.getStatus().previousInterrupted, false);
});

test('retention counts completed native and Python reports together, preserves active files', t => {
  const root = fixture(t);
  const dir = path.join(root, 'diagnostics');
  for (let index = 0; index < 12; index += 1) writeReport(dir, `${index % 2 ? 'python' : 'electron/reports'}/${index}.log`, 5, 60000 + index);
  const active = writeReport(dir, 'python/backend-1-uuid.active.log', 8);
  const collector = create(root);
  const result = collector.cleanup();
  assert.equal(result.completedRecords, 10);
  assert.equal(result.totalBytes, 58);
  assert.equal(fs.existsSync(active), true);
});

test('retention removes oldest completed records for total byte budget including active bytes', t => {
  const root = fixture(t);
  const dir = path.join(root, 'diagnostics');
  const old = writeReport(dir, 'electron/reports/old.dmp', 30, 70000);
  const recent = writeReport(dir, 'python/recent.log', 20, 60000);
  const active = writeReport(dir, 'python/backend.active.log', 40);
  const collector = create(root, { maxBytes: 65 });
  const result = collector.cleanup();
  assert.equal(fs.existsSync(old), false);
  assert.equal(fs.existsSync(recent), true);
  assert.equal(fs.existsSync(active), true);
  assert.equal(result.totalBytes, 60);
});

test('retention never traverses symlinks or deletes fresh native dumps', t => {
  const root = fixture(t);
  const outside = fixture(t);
  const dir = path.join(root, 'diagnostics');
  const external = writeReport(outside, 'private.log', 25);
  fs.mkdirSync(dir, { recursive: true });
  fs.symlinkSync(outside, path.join(dir, 'linked'), process.platform === 'win32' ? 'junction' : 'dir');
  const fresh = writeReport(dir, 'electron/pending/current.dmp', 25, 0);
  create(root, { maxBytes: 1 }).cleanup();
  assert.equal(fs.existsSync(external), true);
  assert.equal(fs.existsSync(fresh), true);
});

test('storage failure is contained and exposed without filesystem exception text', t => {
  const root = fixture(t);
  fs.writeFileSync(path.join(root, 'diagnostics'), 'not a directory');
  const collector = create(root);
  assert.equal(collector.startSession(), false);
  assert.equal(collector.getStatus().available, false);
  assert.doesNotThrow(() => collector.recordExit('backend', { reason: 'crashed', exitCode: 1 }));
});

test('abnormal exit records contain only bounded enum metadata, not untrusted text', t => {
  const root = fixture(t);
  const collector = create(root);
  collector.startSession();
  assert.equal(collector.recordExit('renderer', { reason: 'clean-exit', exitCode: 0 }), false);
  assert.equal(collector.recordExit('backend', { reason: 'api-key-secret', exitCode: 12, error: 'secret' }), true);
  const records = fs.readdirSync(path.join(root, 'diagnostics', 'incidents')).filter(name => name.endsWith('.json'));
  assert.equal(records.length, 1);
  const value = fs.readFileSync(path.join(root, 'diagnostics', 'incidents', records[0]), 'utf8');
  assert.doesNotMatch(value, /api-key-secret|secret/);
  assert.equal(JSON.parse(value).exitCode, 12);
  collector.markClean();
});

test('backend observer catches exit once and skips intentional shutdown', t => {
  const root = fixture(t);
  const collector = create(root);
  const child = new EventEmitter();
  collector.observeBackend(child);
  child.emit('exit', 5, null);
  child.emit('exit', 5, null);
  const dir = path.join(root, 'diagnostics', 'incidents');
  assert.equal(fs.readdirSync(dir).length, 1);
  const second = new EventEmitter();
  collector.observeBackend(second);
  collector.beginShutdown();
  second.emit('exit', 9, null);
  assert.equal(fs.readdirSync(dir).length, 1);
});

test('IPC checks the trusted main window and rejects arguments before opening a directory', async t => {
  const root = fixture(t);
  const collector = create(root);
  const handlers = {};
  const sender = {};
  const opened = [];
  collector.installIpc({ ipcMain: { handle: (channel, handler) => { handlers[channel] = handler; } }, getWebContents: () => sender, isTrustedSender: event => event.senderFrame?.url === 'vantage://app/index.html', shell: { openPath: async value => { opened.push(value); return ''; } } });
  assert.throws(() => handlers['diagnostics:get-status']({ sender: {} }), /Unauthorized/);
  const event = { sender, senderFrame: { url: 'vantage://app/index.html' } };
  assert.throws(() => handlers['diagnostics:get-status'](event, 'arbitrary'), /arguments/);
  assert.equal(handlers['diagnostics:get-status'](event).localOnly, true);
  assert.deepEqual(await handlers['diagnostics:open-directory'](event), { opened: true });
  assert.deepEqual(opened, [path.join(root, 'diagnostics')]);
});

test('retention revalidates parents when a directory is swapped for a symlink after enumeration', t => {
  const root = fixture(t);
  const outside = fixture(t);
  const dir = path.join(root, 'diagnostics');
  const original = writeReport(dir, 'electron/reports/old.dmp', 25);
  const external = writeReport(outside, 'old.dmp', 25);
  const originalStat = fs.statSync(original);
  fs.utimesSync(external, originalStat.atime, originalStat.mtime);
  let swapped = false;
  const collector = create(root, { maxBytes: 1, now: () => {
    if (!swapped) {
      swapped = true;
      fs.renameSync(path.dirname(original), path.join(dir, 'electron', 'saved'));
      fs.symlinkSync(outside, path.dirname(original), process.platform === 'win32' ? 'junction' : 'dir');
    }
    return Date.now();
  } });
  collector.cleanup();
  assert.equal(fs.existsSync(external), true);
});

test('concurrent backend pruning does not mark storage unavailable', t => {
  const root = fixture(t);
  const filename = writeReport(path.join(root, 'diagnostics'), 'electron/reports/old.dmp', 25);
  const collector = create(root, { maxBytes: 1, now: () => {
    if (fs.existsSync(filename)) fs.unlinkSync(filename);
    return Date.now();
  } });
  collector.cleanup();
  assert.equal(collector.getStatus().available, true);
});

test('unfinished Crashpad new-directory dumps remain active regardless of age', t => {
  const root = fixture(t);
  const filename = writeReport(path.join(root, 'diagnostics'), 'electron/new/still-writing.dmp', 25, 120000);
  const result = create(root, { maxBytes: 1 }).cleanup();
  assert.equal(fs.existsSync(filename), true);
  assert.equal(result.overBudget, true);
});

test('Windows native writer without delete sharing is preserved without collector failure', { skip: process.platform !== 'win32' }, async t => {
  const root = fixture(t);
  const filename = writeReport(path.join(root, 'diagnostics'), 'electron/reports/still-writing.dmp', 25, 120000);
  const completed = writeReport(path.join(root, 'diagnostics'), 'python/completed.log', 25, 60000);
  const child = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', "$h=[IO.File]::Open($env:VANTAGE_TEST_DUMP,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite);[Console]::WriteLine('ready');[Console]::ReadLine()|Out-Null;$h.Dispose()"], { env: { ...process.env, VANTAGE_TEST_DUMP: filename }, windowsHide: true });
  try {
    await once(child.stdout, 'data');
    const collector = create(root, { maxBytes: 1 });
    collector.cleanup();
    assert.equal(fs.existsSync(filename), true);
    assert.equal(fs.existsSync(completed), false);
    assert.equal(collector.getStatus().available, true);
  } finally {
    child.stdin.end('\n');
    await once(child, 'exit');
  }
});

test('main starts the collector only for the primary instance, before any BrowserWindow', () => {
  const source = fs.readFileSync(new URL('../../main.cjs', import.meta.url), 'utf8');
  const lock = source.indexOf('const gotTheLock = app.requestSingleInstanceLock();');
  assert.ok(lock > 0);
  assert.doesNotMatch(source.slice(0, lock), /createCrashDiagnostics\(\{/);
  assert.match(source.slice(lock), /crashDiagnostics\.startNativeCollector\(\{ app, crashReporter \}\)/);
  const init = source.indexOf('crashDiagnostics.startNativeCollector');
  assert.ok(init < source.indexOf('app.whenReady()', lock));
  assert.match(source, /app\.on\('quit',[^]*crashDiagnostics\?\.markClean\(\)/);
  assert.match(source, /onSpawned:\s*child\s*=>\s*\{\s*bundledBackendProcess = child;\s*crashDiagnostics\.observeBackend\(child\)/);
});

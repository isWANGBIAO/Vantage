const fs = require('node:fs');
const path = require('node:path');

const DEFAULT_MAX_BYTES = 10 * 1024 * 1024;
const DEFAULT_MAX_FILES = 6;
const ELECTRON_LOG_PATTERN = /^electron.*\.log.*$/;
const UTF8_BOUNDARY_BYTES = 3;

let temporaryFileSequence = 0;

function utf8SequenceLength(firstByte) {
  if (firstByte <= 0x7f) {
    return 1;
  }
  if (firstByte >= 0xc2 && firstByte <= 0xdf) {
    return 2;
  }
  if (firstByte >= 0xe0 && firstByte <= 0xef) {
    return 3;
  }
  if (firstByte >= 0xf0 && firstByte <= 0xf4) {
    return 4;
  }
  return 0;
}

function trimIncompleteUtf8End(buffer) {
  if (buffer.length === 0) {
    return buffer;
  }

  let sequenceStart = buffer.length - 1;
  while (
    sequenceStart >= 0
    && (buffer[sequenceStart] & 0xc0) === 0x80
  ) {
    sequenceStart -= 1;
  }

  if (sequenceStart < 0) {
    return buffer.subarray(0, 0);
  }

  const sequenceLength = utf8SequenceLength(buffer[sequenceStart]);
  const availableBytes = buffer.length - sequenceStart;
  if (sequenceLength === 0) {
    return buffer.subarray(0, sequenceStart);
  }
  if (availableBytes < sequenceLength) {
    return buffer.subarray(0, sequenceStart);
  }
  if (availableBytes > sequenceLength) {
    return buffer.subarray(0, sequenceStart + sequenceLength);
  }
  return buffer;
}

function boundUtf8Tail(buffer, maxBytes) {
  let bounded = buffer;
  if (buffer.length > maxBytes) {
    let start = buffer.length - maxBytes;
    while (start < buffer.length && (buffer[start] & 0xc0) === 0x80) {
      start += 1;
    }
    bounded = buffer.subarray(start);
  }

  return trimIncompleteUtf8End(bounded);
}

function nextRotationPath(logFile) {
  let suffix = 1;
  let candidate = `${logFile}.${suffix}`;

  while (fs.existsSync(candidate)) {
    suffix += 1;
    candidate = `${logFile}.${suffix}`;
  }

  return candidate;
}

function collectElectronLogs(logFile) {
  const logDirectory = path.dirname(logFile);
  const activePath = path.resolve(logFile);
  const candidates = [];
  let names;

  try {
    names = fs.readdirSync(logDirectory);
  } catch {
    return candidates;
  }

  for (const name of names) {
    if (!ELECTRON_LOG_PATTERN.test(name)) {
      continue;
    }

    const file = path.join(logDirectory, name);
    try {
      const stats = fs.lstatSync(file);
      if (stats.isFile()) {
        candidates.push({
          file,
          modified: stats.mtimeMs,
          stats,
          isActive: path.resolve(file) === activePath,
        });
      }
    } catch {
      // A concurrently removed file needs no further retention work.
    }
  }

  return candidates;
}

function pruneElectronLogs(logFile, maxFiles, protectedFiles = new Set()) {
  const candidates = collectElectronLogs(logFile);

  candidates.sort((left, right) => {
    if (left.isActive !== right.isActive) {
      return left.isActive ? 1 : -1;
    }
    return left.modified - right.modified || left.file.localeCompare(right.file);
  });

  let excess = candidates.length - maxFiles;
  for (const candidate of candidates) {
    if (excess <= 0) {
      break;
    }
    if (
      candidate.isActive
      || protectedFiles.has(path.resolve(candidate.file))
    ) {
      continue;
    }

    try {
      fs.unlinkSync(candidate.file);
      excess -= 1;
    } catch {
      // Retention is best-effort and must never re-enter the logger.
    }
  }
}

function sameFileVersion(left, right) {
  return (
    left.isFile()
    && right.isFile()
    && left.dev === right.dev
    && left.ino === right.ino
    && left.size === right.size
    && left.mtimeMs === right.mtimeMs
    && left.ctimeMs === right.ctimeMs
  );
}

function readBoundedUtf8Tail(descriptor, size, maxBytes) {
  const readLength = Math.min(size, maxBytes + UTF8_BOUNDARY_BYTES);
  const buffer = Buffer.allocUnsafe(readLength);
  const start = size - readLength;
  let totalBytesRead = 0;

  while (totalBytesRead < readLength) {
    const bytesRead = fs.readSync(
      descriptor,
      buffer,
      totalBytesRead,
      readLength - totalBytesRead,
      start + totalBytesRead,
    );
    if (bytesRead === 0) {
      break;
    }
    totalBytesRead += bytesRead;
  }

  return boundUtf8Tail(buffer.subarray(0, totalBytesRead), maxBytes);
}

function readStableBoundedUtf8Tail(candidate, maxBytes) {
  const beforeOpen = fs.lstatSync(candidate.file);
  if (
    !sameFileVersion(candidate.stats, beforeOpen)
    || beforeOpen.size <= maxBytes
  ) {
    return null;
  }

  const descriptor = fs.openSync(candidate.file, 'r');
  try {
    const opened = fs.fstatSync(descriptor);
    if (!sameFileVersion(beforeOpen, opened) || opened.size <= maxBytes) {
      return null;
    }

    const tail = readBoundedUtf8Tail(descriptor, opened.size, maxBytes);
    const afterRead = fs.fstatSync(descriptor);
    if (!sameFileVersion(opened, afterRead)) {
      return null;
    }

    return {
      stats: afterRead,
      tail,
    };
  } finally {
    fs.closeSync(descriptor);
  }
}

function nextTemporaryPath(file) {
  temporaryFileSequence += 1;
  return path.join(
    path.dirname(file),
    `.${path.basename(file)}.${process.pid}.${temporaryFileSequence}.tmp`,
  );
}

function replaceWithBoundedTail(candidate, maxBytes) {
  const stableTail = readStableBoundedUtf8Tail(candidate, maxBytes);
  if (!stableTail) {
    return false;
  }

  const { stats, tail } = stableTail;
  let temporaryPath;

  try {
    for (let attempt = 0; attempt < 10; attempt += 1) {
      temporaryPath = nextTemporaryPath(candidate.file);
      try {
        fs.writeFileSync(temporaryPath, tail, { flag: 'wx' });
        break;
      } catch (error) {
        if (error.code !== 'EEXIST') {
          throw error;
        }
        temporaryPath = null;
      }
    }

    if (!temporaryPath) {
      return;
    }

    try {
      fs.chmodSync(temporaryPath, stats.mode);
    } catch {
      // Preserving permissions is best-effort on Windows and network volumes.
    }
    try {
      fs.utimesSync(
        temporaryPath,
        stats.atime,
        stats.mtime,
      );
    } catch {
      // Retaining the old mtime keeps global pruning deterministic when possible.
    }

    const beforeReplace = fs.lstatSync(candidate.file);
    if (!sameFileVersion(stats, beforeReplace)) {
      return false;
    }

    // A same-directory rename provides an atomic replacement to other readers.
    fs.renameSync(temporaryPath, candidate.file);
    temporaryPath = null;

    try {
      fs.utimesSync(
        candidate.file,
        stats.atime,
        stats.mtime,
      );
    } catch {
      // The replacement is already safe even if timestamp restoration fails.
    }
  } finally {
    if (temporaryPath) {
      try {
        fs.unlinkSync(temporaryPath);
      } catch {
        // Never route cleanup failures back through the logger.
      }
    }
  }

  return true;
}

function cleanupElectronLogs(logFile, maxBytes, maxFiles) {
  const candidates = collectElectronLogs(logFile);
  const protectedFiles = new Set();

  for (const candidate of candidates) {
    if (candidate.stats.size <= maxBytes) {
      continue;
    }
    try {
      if (!replaceWithBoundedTail(candidate, maxBytes)) {
        protectedFiles.add(path.resolve(candidate.file));
      }
    } catch {
      // A disappearing or inaccessible legacy log must not block application startup.
      protectedFiles.add(path.resolve(candidate.file));
    }
  }

  pruneElectronLogs(logFile, maxFiles, protectedFiles);
}

function appendBoundedEntry(logFile, entryBuffer, maxBytes, maxFiles) {
  let currentSize = 0;
  try {
    currentSize = fs.statSync(logFile).size;
  } catch (error) {
    if (error.code !== 'ENOENT') {
      throw error;
    }
  }

  if (currentSize > 0 && currentSize + entryBuffer.length > maxBytes) {
    fs.renameSync(logFile, nextRotationPath(logFile));
  }

  fs.appendFileSync(logFile, entryBuffer);
  pruneElectronLogs(logFile, maxFiles);
}

function createBoundedLogger({
  logFile,
  consoleObject = console,
  maxBytes = DEFAULT_MAX_BYTES,
  maxFiles = DEFAULT_MAX_FILES,
  stdout,
  stderr,
}) {
  let consoleMirroringEnabled = true;
  let disposed = false;
  const guardedStreams = new Set();
  const resolvedStreams = [
    stdout === undefined
      ? (consoleObject === console ? process.stdout : null)
      : stdout,
    stderr === undefined
      ? (consoleObject === console ? process.stderr : null)
      : stderr,
  ];

  function disableConsoleMirroring() {
    consoleMirroringEnabled = false;
  }

  for (const stream of resolvedStreams) {
    if (!stream || guardedStreams.has(stream)) {
      continue;
    }
    try {
      stream.on('error', disableConsoleMirroring);
      guardedStreams.add(stream);
    } catch {
      disableConsoleMirroring();
    }
  }

  function outputStreamUnavailable() {
    for (const stream of resolvedStreams) {
      if (stream && (stream.destroyed === true || stream.writable === false)) {
        return true;
      }
    }
    return false;
  }

  function writeLog(level, message, error = null) {
    const timestamp = new Date().toISOString();
    let logEntry = `[${timestamp}] [${level}] ${message}`;

    if (error) {
      logEntry += `\n  Stack: ${error.stack || error}`;
    }

    logEntry += '\n';
    const entryBuffer = boundUtf8Tail(Buffer.from(logEntry, 'utf8'), maxBytes);
    try {
      appendBoundedEntry(logFile, entryBuffer, maxBytes, maxFiles);
    } catch {
      // Logging failures are isolated here so an exception handler cannot recurse.
    }

    if (
      disposed
      || !consoleMirroringEnabled
      || outputStreamUnavailable()
    ) {
      consoleMirroringEnabled = false;
      return;
    }

    try {
      if (level === 'ERROR') {
        consoleObject.error(logEntry);
      } else {
        consoleObject.log(logEntry);
      }
    } catch {
      consoleMirroringEnabled = false;
    }
  }

  function cleanup() {
    try {
      cleanupElectronLogs(logFile, maxBytes, maxFiles);
    } catch {
      // Startup cleanup is isolated from both the application and this logger.
    }
  }

  function dispose() {
    if (disposed) {
      return;
    }
    disposed = true;
    consoleMirroringEnabled = false;

    for (const stream of guardedStreams) {
      try {
        if (typeof stream.off === 'function') {
          stream.off('error', disableConsoleMirroring);
        } else {
          stream.removeListener('error', disableConsoleMirroring);
        }
      } catch {
        // Stream teardown is best-effort and must never reach the logger.
      }
    }
    guardedStreams.clear();
  }

  return {
    info: (message) => writeLog('INFO', message),
    warn: (message) => writeLog('WARN', message),
    error: (message, error = null) => writeLog('ERROR', message, error),
    cleanup,
    dispose,
  };
}

module.exports = {
  createBoundedLogger,
  DEFAULT_MAX_BYTES,
  DEFAULT_MAX_FILES,
};

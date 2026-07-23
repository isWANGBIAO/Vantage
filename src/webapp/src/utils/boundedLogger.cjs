const fs = require('node:fs');
const path = require('node:path');

const DEFAULT_MAX_BYTES = 10 * 1024 * 1024;
const DEFAULT_MAX_FILES = 6;
const ELECTRON_LOG_PATTERN = /^electron.*\.log.*$/;
const UTF8_BOUNDARY_BYTES = 3;

let temporaryFileSequence = 0;

function boundUtf8Tail(buffer, maxBytes) {
  if (buffer.length <= maxBytes) {
    return buffer;
  }

  let start = buffer.length - maxBytes;
  while (start < buffer.length && (buffer[start] & 0xc0) === 0x80) {
    start += 1;
  }
  return buffer.subarray(start);
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

function pruneElectronLogs(logFile, maxFiles) {
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
    if (candidate.isActive) {
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

function readBoundedUtf8Tail(file, size, maxBytes) {
  const readLength = Math.min(size, maxBytes + UTF8_BOUNDARY_BYTES);
  const buffer = Buffer.allocUnsafe(readLength);
  const start = size - readLength;
  const descriptor = fs.openSync(file, 'r');
  let totalBytesRead = 0;

  try {
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
  } finally {
    fs.closeSync(descriptor);
  }

  return boundUtf8Tail(buffer.subarray(0, totalBytesRead), maxBytes);
}

function nextTemporaryPath(file) {
  temporaryFileSequence += 1;
  return path.join(
    path.dirname(file),
    `.${path.basename(file)}.${process.pid}.${temporaryFileSequence}.tmp`,
  );
}

function replaceWithBoundedTail(candidate, maxBytes) {
  const tail = readBoundedUtf8Tail(
    candidate.file,
    candidate.stats.size,
    maxBytes,
  );
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
      fs.chmodSync(temporaryPath, candidate.stats.mode);
    } catch {
      // Preserving permissions is best-effort on Windows and network volumes.
    }
    try {
      fs.utimesSync(
        temporaryPath,
        candidate.stats.atime,
        candidate.stats.mtime,
      );
    } catch {
      // Retaining the old mtime keeps global pruning deterministic when possible.
    }

    // A same-directory rename provides an atomic replacement to other readers.
    fs.renameSync(temporaryPath, candidate.file);
    temporaryPath = null;

    try {
      fs.utimesSync(
        candidate.file,
        candidate.stats.atime,
        candidate.stats.mtime,
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
}

function cleanupElectronLogs(logFile, maxBytes, maxFiles) {
  const candidates = collectElectronLogs(logFile);

  for (const candidate of candidates) {
    if (candidate.stats.size <= maxBytes) {
      continue;
    }
    try {
      replaceWithBoundedTail(candidate, maxBytes);
    } catch {
      // A disappearing or inaccessible legacy log must not block application startup.
    }
  }

  pruneElectronLogs(logFile, maxFiles);
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
